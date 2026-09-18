import type { Event } from "@opencode-ai/sdk"
import type { Hooks, PluginInput } from "@opencode-ai/plugin"
import { SessionTracker } from "./state"

export type LogicalEventType =
  | "permission"
  | "question"
  | "complete"
  | "subagent_complete"
  | "error"
  | "cancelled"

export interface LogicalEvent {
  event: LogicalEventType
  sessionTitle: string | null
  durationMs: number | null
}

type PermissionAskedEvent = {
  type: "permission.asked"
  properties: { sessionID: string }
}

type RuntimeEvent = Event | PermissionAskedEvent
type EmitEvent = (event: LogicalEvent) => void

export type EventHookScheduler = {
  setTimeout(callback: () => void | Promise<void>, delayMs: number): unknown
  clearTimeout(handle: unknown): void
}

export interface EventHookOptions {
  now?: () => number
  scheduler?: EventHookScheduler
  delayMs?: number
  directory?: string
}

const DEFAULT_NOTIFICATION_DELAY_MS = 8_000

function createDefaultScheduler(): EventHookScheduler {
  return {
    setTimeout: (callback, delayMs) => setTimeout(callback, delayMs),
    clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  }
}

async function refreshSession(
  client: PluginInput["client"],
  tracker: SessionTracker,
  sessionID: string,
): Promise<void> {
  try {
    const response = await client.session.get({ path: { id: sessionID } })
    const session = response.data
    if (session) {
      tracker.updateSession(sessionID, session.title || null, Boolean(session.parentID))
    }
  } catch {
    // Completion still has useful semantics when session metadata is unavailable.
  }
}

export function createEventHooks(
  client: PluginInput["client"],
  emit: EmitEvent,
  options: EventHookOptions = {},
): Pick<Hooks, "event" | "permission.ask" | "tool.execute.before"> {
  const tracker = new SessionTracker()
  const now = options.now ?? Date.now
  const scheduler = options.scheduler ?? createDefaultScheduler()
  const delayMs = options.delayMs ?? DEFAULT_NOTIFICATION_DELAY_MS
  const pendingNotifications = new Map<string, unknown>()

  async function readTailMessageId(sessionID: string): Promise<string | undefined> {
    try {
      const response = await client.session.messages({
        path: { id: sessionID },
        query: options.directory ? { directory: options.directory } : {},
      })
      return (response.data ?? []).at(-1)?.info?.id
    } catch {
      return undefined
    }
  }

  // Mirror the auto-continue plugin's delayed tail review for every
  // session-stopped notification: hold it, then re-read the session tail. An
  // unchanged tail means the session really stopped; a changed tail means
  // auto-continue or the user already resumed it, so the notification is dropped.
  async function scheduleDelayedNotification(
    sessionID: string,
    notification: LogicalEvent,
  ): Promise<void> {
    const existing = pendingNotifications.get(sessionID)
    if (existing !== undefined) {
      scheduler.clearTimeout(existing)
      pendingNotifications.delete(sessionID)
    }

    const tailMessageId = await readTailMessageId(sessionID)
    if (tailMessageId === undefined) {
      // An unverifiable tail still notifies: a false alarm is cheaper than a missed stop.
      emit(notification)
      return
    }

    const timer = scheduler.setTimeout(async () => {
      if (pendingNotifications.get(sessionID) !== timer) {
        return
      }
      pendingNotifications.delete(sessionID)

      const currentTailId = await readTailMessageId(sessionID)
      if (currentTailId !== undefined && currentTailId !== tailMessageId) {
        return
      }
      emit(notification)
    }, delayMs)

    pendingNotifications.set(sessionID, timer)
  }

  return {
    event: async ({ event }) => {
      const runtimeEvent = event as RuntimeEvent

      if (runtimeEvent.type === "session.created" || runtimeEvent.type === "session.updated") {
        const { info } = runtimeEvent.properties
        tracker.updateSession(info.id, info.title || null, Boolean(info.parentID))
        return
      }

      if (runtimeEvent.type === "session.deleted") {
        tracker.deleteSession(runtimeEvent.properties.info.id)
        return
      }

      if (runtimeEvent.type === "permission.asked") {
        const sessionID = runtimeEvent.properties.sessionID
        if (!tracker.shouldSuppressPermission(sessionID, now())) {
          emit({
            event: "permission",
            sessionTitle: tracker.getSession(sessionID)?.title ?? null,
            durationMs: null,
          })
        }
        return
      }

      if (runtimeEvent.type === "session.status") {
        const { sessionID, status } = runtimeEvent.properties
        const completion = tracker.updateStatus(sessionID, status, now())
        if (!completion) {
          return
        }

        if (completion.title === null || completion.isChild === null) {
          await refreshSession(client, tracker, sessionID)
        }
        const session = tracker.getSession(sessionID)
        await scheduleDelayedNotification(sessionID, {
          event: session?.isChild === true ? "subagent_complete" : "complete",
          sessionTitle: session?.title ?? completion.title,
          durationMs: completion.durationMs,
        })
        return
      }

      if (runtimeEvent.type === "session.error") {
        const sessionID = runtimeEvent.properties.sessionID ?? null
        const sessionTitle = sessionID ? tracker.getSession(sessionID)?.title ?? null : null
        if (sessionID) {
          tracker.markError(sessionID)
        }

        const errorName = (runtimeEvent.properties.error as { name?: string } | undefined)?.name
        if (errorName === "MessageAbortedError" || errorName === "AbortError") {
          emit({ event: "cancelled", sessionTitle, durationMs: null })
          return
        }

        if (sessionID) {
          await scheduleDelayedNotification(sessionID, { event: "error", sessionTitle, durationMs: null })
          return
        }

        emit({ event: "error", sessionTitle, durationMs: null })
      }
    },

    "permission.ask": async (input) => {
      if (!tracker.shouldSuppressPermission(input.sessionID, now())) {
        emit({
          event: "permission",
          sessionTitle: tracker.getSession(input.sessionID)?.title ?? null,
          durationMs: null,
        })
      }
    },

    "tool.execute.before": async (input) => {
      if (input.tool === "question") {
        emit({
          event: "question",
          sessionTitle: tracker.getSession(input.sessionID)?.title ?? null,
          durationMs: null,
        })
      }
    },
  }
}
