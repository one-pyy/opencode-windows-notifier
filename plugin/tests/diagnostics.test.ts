import { expect, test } from "bun:test"
import type { PluginInput } from "@opencode-ai/plugin"
import { createDiagnosticLogger } from "../src/diagnostics"

test("diagnostic logging uses the host log and does not wait for its response", async () => {
  const requests: unknown[] = []
  let release: (() => void) | undefined
  const client = { app: { log: (request: unknown) => {
    requests.push(request)
    return new Promise<void>((resolve) => { release = resolve })
  } } } as unknown as PluginInput["client"]
  const log = createDiagnosticLogger(client, "/project")
  expect(log("notification.emit", { sessionID: "main", event: "complete" })).toBeUndefined()
  expect(requests).toEqual([{
    query: { directory: "/project" },
    body: { service: "opencode-windows-notifier", level: "info", message: "notification.emit", extra: { sessionID: "main", event: "complete" } },
  }])
  release?.()
  await Promise.resolve()
})

test("synchronous and asynchronous host log failures stay isolated", async () => {
  for (const failure of [() => { throw new Error("unavailable") }, () => Promise.reject(new Error("unavailable"))]) {
    const client = { app: { log: failure } } as unknown as PluginInput["client"]
    expect(createDiagnosticLogger(client, "/project")("notification.emit", { sessionID: "main" })).toBeUndefined()
    await Promise.resolve()
  }
})
