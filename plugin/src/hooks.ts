import type { Event } from "@opencode-ai/sdk"
import type { Hooks, PluginInput } from "@opencode-ai/plugin"
import { SessionTracker } from "./state"
import type { DiagnosticLogger } from "./diagnostics"

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
type EmitEvent = (event: LogicalEvent, sessionID?: string | null) => void

export type EventHookScheduler = {
  setTimeout(callback: () => void | Promise<void>, delayMs: number): unknown
  clearTimeout(handle: unknown): void
}

export interface EventHookOptions {
  now?: () => number
  scheduler?: EventHookScheduler
  delayMs?: number
  directory?: string
  log?: DiagnosticLogger
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
  const log = options.log ?? (() => {})

  function notify(notification: LogicalEvent, sessionID: string | null): void {
    log("notification.emit", { sessionID, event: notification.event })
    emit(notification, sessionID)
  }

  async function hasBusyChildren(sessionID: string): Promise<boolean> {
    try {
      const query = options.directory ? { directory: options.directory } : {}
      const children = await client.session.children({ path: { id: sessionID }, query })
      if (!children.data) {
        log("children.unavailable", { sessionID, stage: "children", action: "continue" })
        return false
      }
      if (!children.data?.length) {
        log("children.checked", { sessionID, childCount: 0, busyChildren: [] })
        return false
      }
      const statuses = await client.session.status({ query })
      if (!statuses.data) {
        log("children.unavailable", { sessionID, stage: "status", action: "continue" })
      }
      const busyChildren = children.data.filter((child) => {
        const status = statuses.data?.[child.id]?.type
        return status === "busy" || status === "retry"
      })
      log("children.checked", {
        sessionID,
        childCount: children.data.length,
        busyChildren: busyChildren.map((child) => ({ sessionID: child.id, status: statuses.data?.[child.id]?.type })),
      })
      return busyChildren.length > 0
    } catch {
      log("children.unavailable", { sessionID, stage: "query", action: "continue" })
      // Preserve completion notifications when child status cannot be verified.
      return false
    }
  }

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
      log("notification.replaced", { sessionID, event: notification.event })
    }

    if (notification.event === "complete" && await hasBusyChildren(sessionID)) {
      log("notification.skipped", { sessionID, event: notification.event, reason: "busy_children" })
      return
    }

    const tailMessageId = await readTailMessageId(sessionID)
    if (tailMessageId === undefined) {
      // An unverifiable tail still notifies: a false alarm is cheaper than a missed stop.
      log("tail.unavailable", { sessionID, event: notification.event, stage: "initial", action: "emit" })
      notify(notification, sessionID)
      return
    }

    const timer = scheduler.setTimeout(async () => {
      if (pendingNotifications.get(sessionID) !== timer) {
        log("notification.skipped", { sessionID, event: notification.event, reason: "replaced_timer" })
        return
      }
      pendingNotifications.delete(sessionID)

      const currentTailId = await readTailMessageId(sessionID)
      if (currentTailId !== undefined && currentTailId !== tailMessageId) {
        log("notification.skipped", { sessionID, event: notification.event, reason: "tail_changed", tailMessageId, currentTailId })
        return
      }
      log("tail.reviewed", { sessionID, event: notification.event, tailMessageId, currentTailId: currentTailId ?? null, verified: currentTailId !== undefined })
      notify(notification, sessionID)
    }, delayMs)

    pendingNotifications.set(sessionID, timer)
    log("notification.scheduled", { sessionID, event: notification.event, delayMs, tailMessageId })
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
          notify({
            event: "permission",
            sessionTitle: tracker.getSession(sessionID)?.title ?? null,
            durationMs: null,
          }, sessionID)
        } else {
          log("notification.skipped", { sessionID, event: "permission", reason: "duplicate_permission" })
        }
        return
      }

      if (runtimeEvent.type === "session.status") {
        const { sessionID, status } = runtimeEvent.properties
        const wasActive = tracker.getSession(sessionID)?.active ?? false
        const completion = tracker.updateStatus(sessionID, status, now())
        log("session.status", { sessionID, status: status.type, wasActive, completion: completion !== null })
        if (!completion) {
          if (status.type === "idle") {
            log("notification.skipped", { sessionID, event: "complete", reason: "no_active_transition" })
          }
          return
        }

        if (completion.title === null || completion.isChild === null) {
          await refreshSession(client, tracker, sessionID)
        }
        const session = tracker.getSession(sessionID)
        log("completion.classified", { sessionID, isChild: session?.isChild ?? null, durationMs: completion.durationMs })
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
        log("session.error", { sessionID, cancelled: errorName === "MessageAbortedError" || errorName === "AbortError" })
        if (errorName === "MessageAbortedError" || errorName === "AbortError") {
          notify({ event: "cancelled", sessionTitle, durationMs: null }, sessionID)
          return
        }

        if (sessionID) {
          await scheduleDelayedNotification(sessionID, { event: "error", sessionTitle, durationMs: null })
          return
        }

        notify({ event: "error", sessionTitle, durationMs: null }, sessionID)
      }
    },

    "permission.ask": async (input) => {
      if (!tracker.shouldSuppressPermission(input.sessionID, now())) {
        notify({
          event: "permission",
          sessionTitle: tracker.getSession(input.sessionID)?.title ?? null,
          durationMs: null,
        }, input.sessionID)
      } else {
        log("notification.skipped", { sessionID: input.sessionID, event: "permission", reason: "duplicate_permission" })
      }
    },

    "tool.execute.before": async (input) => {
      if (input.tool === "question") {
        notify({
          event: "question",
          sessionTitle: tracker.getSession(input.sessionID)?.title ?? null,
          durationMs: null,
        }, input.sessionID)
      }
    },
  }
}
