import type { Plugin } from "@opencode-ai/plugin"
import { basename } from "node:path"
import { loadPluginConfig } from "./config"
import { createEventHooks } from "./hooks"
import { buildEventPayload, sendEvent } from "./sender"
import { createDiagnosticLogger } from "./diagnostics"

const WindowsNotifierPlugin: Plugin = async ({ client, directory }) => {
  const config = loadPluginConfig()
  if (!config) {
    return {}
  }

  const projectName = basename(directory) || null
  const log = createDiagnosticLogger(client, directory)
  log("plugin.enabled", { delayMs: config.delayMs, timeoutMs: config.timeoutMs })
  return createEventHooks(
    client,
    (event, sessionID) => {
      sendEvent(config, buildEventPayload(event, projectName), { log, sessionID })
    },
    { delayMs: config.delayMs, directory, log },
  )
}

export default WindowsNotifierPlugin
