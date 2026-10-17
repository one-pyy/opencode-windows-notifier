import type { PluginInput } from "@opencode-ai/plugin"

export type DiagnosticLogger = (message: string, extra: Record<string, unknown>) => void

export function createDiagnosticLogger(client: PluginInput["client"], directory: string): DiagnosticLogger {
  async function write(message: string, extra: Record<string, unknown>): Promise<void> {
    try {
      await client.app.log({
        query: { directory },
        body: { service: "opencode-windows-notifier", level: "info", message, extra },
      })
    } catch {
      // Diagnostics must never interrupt notification handling.
    }
  }
  return (message, extra) => { void write(message, extra) }
}
