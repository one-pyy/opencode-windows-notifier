import type { PluginConfig } from "./config"
import type { LogicalEvent, LogicalEventType } from "./index"

export interface EventPayload {
  event: LogicalEventType
  timestamp: string
  session_title: string | null
  project_name: string | null
  duration_ms: number | null
  message: string
}

const MESSAGE_PREFIX: Record<LogicalEventType, string> = {
  permission: "Session needs permission",
  question: "Session has a question",
  complete: "Session has finished",
  subagent_complete: "Subagent task completed",
  error: "Session encountered an error",
  cancelled: "Session was cancelled",
}

export function buildEventPayload(
  logicalEvent: LogicalEvent,
  projectName: string | null,
  timestamp: Date = new Date(),
): EventPayload {
  const subject = logicalEvent.sessionTitle ?? projectName
  return {
    event: logicalEvent.event,
    timestamp: timestamp.toISOString(),
    session_title: logicalEvent.sessionTitle,
    project_name: projectName,
    duration_ms: logicalEvent.durationMs,
    message: subject ? `${MESSAGE_PREFIX[logicalEvent.event]}: ${subject}` : MESSAGE_PREFIX[logicalEvent.event],
  }
}

async function postEvent(config: PluginConfig, payload: EventPayload): Promise<void> {
  const controller = new AbortController()
  const timer = setTimeout(() => {
    controller.abort()
  }, config.timeoutMs)

  try {
    await fetch(`${config.serverUrl}/v1/events`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
  } catch {
    // Windows notifications are optional; delivery failures must stay invisible to OpenCode.
  } finally {
    clearTimeout(timer)
  }
}

export function sendEvent(config: PluginConfig, payload: EventPayload): void {
  void postEvent(config, payload)
}
