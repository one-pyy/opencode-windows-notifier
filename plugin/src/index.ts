import type { Plugin } from "@opencode-ai/plugin"
import { basename } from "node:path"
import { loadPluginConfig } from "./config"
import { createEventHooks } from "./hooks"
import { buildEventPayload, sendEvent } from "./sender"

const WindowsNotifierPlugin: Plugin = async ({ client, directory }) => {
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
