import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

export interface PluginConfig {
  serverUrl: string
  token: string
  timeoutMs: number
}

type ConfigFile = {
  server_url: string
  token: string
  timeout_ms?: number
}

const CONFIG_KEYS = new Set(["server_url", "token", "timeout_ms"])

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

export function getPluginConfigPath(
  env: NodeJS.ProcessEnv = process.env,
  homeDirectory: string = homedir(),
): string {
  return env.OPENCODE_WINDOWS_NOTIFIER_CONFIG_PATH
    ?? join(homeDirectory, ".config", "opencode", "opencode-windows-notifier.json")
}

export function parsePluginConfig(value: unknown): PluginConfig {
  if (!isRecord(value)) {
    throw new Error("configuration must be a JSON object")
  }

  const unknownKeys = Object.keys(value).filter((key) => !CONFIG_KEYS.has(key))
  if (unknownKeys.length > 0) {
    throw new Error(`unknown configuration key: ${unknownKeys[0]}`)
  }

  const file = value as ConfigFile
  if (typeof file.server_url !== "string") {
    throw new Error("server_url must be an HTTP URL")
  }

  let serverUrl: URL
  try {
    serverUrl = new URL(file.server_url)
  } catch {
    throw new Error("server_url must be an HTTP URL")
  }
  if (!['http:', 'https:'].includes(serverUrl.protocol) || serverUrl.username || serverUrl.password) {
    throw new Error("server_url must be an HTTP URL without credentials")
  }
  if (serverUrl.search || serverUrl.hash || /\/v1\/events\/?$/.test(serverUrl.pathname)) {
    throw new Error("server_url must not include query, fragment, or /v1/events")
  }

  if (typeof file.token !== "string" || file.token.trim().length === 0) {
    throw new Error("token must be a non-empty string")
  }

  const timeoutMs = file.timeout_ms ?? 500
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 2_000) {
    throw new Error("timeout_ms must be an integer from 100 through 2000")
  }

  return {
    serverUrl: serverUrl.toString().replace(/\/$/, ""),
    token: file.token,
    timeoutMs,
  }
}

export function loadPluginConfig(
  configPath: string = getPluginConfigPath(),
  logError: (message: string) => void = console.error,
): PluginConfig | null {
  try {
    return parsePluginConfig(JSON.parse(readFileSync(configPath, "utf8")))
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown configuration error"
    logError(`[opencode-windows-notifier] Disabled: ${message}`)
    return null
  }
}
