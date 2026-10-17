import type { PluginConfig } from "./config"
import type { LogicalEvent, LogicalEventType } from "./hooks"
import type { DiagnosticLogger } from "./diagnostics"

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

interface DeliveryDiagnostics {
  sessionID?: string | null
  log?: DiagnosticLogger
}

async function postEvent(config: PluginConfig, payload: EventPayload, diagnostics: DeliveryDiagnostics): Promise<void> {
  const log = diagnostics.log ?? (() => {})
  const context = { sessionID: diagnostics.sessionID ?? null, event: payload.event }
  const startedAt = Date.now()
  const controller = new AbortController()
  const timer = setTimeout(() => {
    controller.abort()
  }, config.timeoutMs)

  try {
    log("delivery.started", { ...context, timeoutMs: config.timeoutMs })
    const response = await fetch(`${config.serverUrl}/v1/events`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    log("delivery.finished", { ...context, result: response.ok ? "accepted" : "http_error", status: response.status, elapsedMs: Date.now() - startedAt })
  } catch {
    log("delivery.finished", { ...context, result: controller.signal.aborted ? "timeout" : "network_error", elapsedMs: Date.now() - startedAt })
    // Windows notifications are optional; delivery failures must stay invisible to OpenCode.
  } finally {
    clearTimeout(timer)
  }
}

export function sendEvent(config: PluginConfig, payload: EventPayload, diagnostics: DeliveryDiagnostics = {}): void {
  void postEvent(config, payload, diagnostics)
}
