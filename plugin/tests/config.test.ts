import { afterEach, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { getPluginConfigPath, loadPluginConfig, parsePluginConfig } from "../src/config"

const temporaryDirectories: string[] = []

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true })
  }
})

describe("plugin configuration", () => {
  test("parses the minimal configuration and applies the default timeout", () => {
    expect(parsePluginConfig({ server_url: "http://172.20.48.1:8765", token: "secret" })).toEqual({
      serverUrl: "http://172.20.48.1:8765",
      token: "secret",
      timeoutMs: 500,
      delayMs: 8_000,
    })
  })

  test("accepts an explicit error delay", () => {
    expect(
      parsePluginConfig({ server_url: "http://172.20.48.1:8765", token: "secret", delay_ms: 12_000 }),
    ).toEqual({
      serverUrl: "http://172.20.48.1:8765",
      token: "secret",
      timeoutMs: 500,
      delayMs: 12_000,
    })
  })

  test("uses the explicit path or the user home, never a project directory", () => {
    expect(getPluginConfigPath({ OPENCODE_WINDOWS_NOTIFIER_CONFIG_PATH: "/tmp/notify.json" }, "/home/user"))
      .toBe("/tmp/notify.json")
    expect(getPluginConfigPath({}, "/home/user"))
      .toBe("/home/user/.config/opencode/opencode-windows-notifier.json")
  })

  test("rejects unknown keys and invalid values", () => {
    const invalidValues = [
      { server_url: "not-a-url", token: "secret" },
      { server_url: "ftp://host", token: "secret" },
      { server_url: "http://host/v1/events", token: "secret" },
      { server_url: "http://host", token: "" },
      { server_url: "http://host", token: "secret", timeout_ms: 99 },
      { server_url: "http://host", token: "secret", timeout_ms: 2_001 },
      { server_url: "http://host", token: "secret", delay_ms: 999 },
      { server_url: "http://host", token: "secret", delay_ms: 60_001 },
      { server_url: "http://host", token: "secret", delay_ms: "8000" },
      { server_url: "http://host", token: "secret", extra: true },
    ]
    for (const value of invalidValues) {
      expect(() => parsePluginConfig(value)).toThrow()
    }
  })

  test("a missing or damaged file disables the plugin with one safe error", () => {
    const directory = mkdtempSync(join(tmpdir(), "opencode-windows-notifier-"))
    temporaryDirectories.push(directory)
    const errors: string[] = []
    expect(loadPluginConfig(join(directory, "missing.json"), (message) => errors.push(message))).toBeNull()
    expect(errors).toHaveLength(1)

    const configPath = join(directory, "config.json")
    writeFileSync(configPath, "{broken")
    expect(loadPluginConfig(configPath, (message) => errors.push(message))).toBeNull()
    expect(errors).toHaveLength(2)
    expect(errors.join(" ")).not.toContain("secret")
  })
})
