import type { Event } from "@opencode-ai/sdk"
import type { Hooks, Plugin, PluginInput } from "@opencode-ai/plugin"
import { basename } from "node:path"
import { loadPluginConfig } from "./config"
import { buildEventPayload, sendEvent } from "./sender"
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
  now: () => number = Date.now,
): Pick<Hooks, "event" | "permission.ask" | "tool.execute.before"> {
  const tracker = new SessionTracker()

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
        emit({
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
        emit({
          event: errorName === "MessageAbortedError" || errorName === "AbortError" ? "cancelled" : "error",
          sessionTitle,
          durationMs: null,
        })
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

export const WindowsNotifierPlugin: Plugin = async ({ client, directory }) => {
  const config = loadPluginConfig()
  if (!config) {
    return {}
  }

  const projectName = basename(directory) || null
  return createEventHooks(client, (event) => {
    sendEvent(config, buildEventPayload(event, projectName))
  })
}

export default WindowsNotifierPlugin
