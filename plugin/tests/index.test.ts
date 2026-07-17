import { describe, expect, test } from "bun:test"
import type { Event } from "@opencode-ai/sdk"
import type { Hooks, PluginInput } from "@opencode-ai/plugin"
import { createEventHooks, type LogicalEvent } from "../src/index"

function createHarness(sessions: Record<string, { title: string; parentID?: string }> = {}) {
  const emitted: LogicalEvent[] = []
  let clock = 1_000
  const client = {
    session: {
      get: async ({ path }: { path: { id: string } }) => ({ data: sessions[path.id] }),
    },
  } as unknown as PluginInput["client"]
  const hooks = createEventHooks(client, (event) => emitted.push(event), () => clock)

  return {
    emitted,
    hooks,
    setClock(value: number) {
      clock = value
    },
  }
}

async function publish(hooks: Pick<Hooks, "event">, event: unknown): Promise<void> {
  await hooks.event?.({ event: event as Event })
}

describe("OpenCode event mapping", () => {
  test("busy to idle emits one main completion", async () => {
    const harness = createHarness()
    await publish(harness.hooks, { type: "session.created", properties: { info: { id: "main", title: "Build feature" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    harness.setClock(1_250)
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })

    expect(harness.emitted).toEqual([{ event: "complete", sessionTitle: "Build feature", durationMs: 250 }])
  })

  test("unknown metadata is refreshed before child completion", async () => {
    const harness = createHarness({ child: { title: "Inspect types", parentID: "main" } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "busy" } } })
    harness.setClock(1_100)
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "idle" } } })

    expect(harness.emitted).toEqual([{ event: "subagent_complete", sessionTitle: "Inspect types", durationMs: 100 }])
  })

  test("error and both abort names suppress later completion", async () => {
    for (const [name, expected] of [
      ["UnknownError", "error"],
      ["MessageAbortedError", "cancelled"],
      ["AbortError", "cancelled"],
    ] as const) {
      const harness = createHarness()
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: name, status: { type: "busy" } } })
      await publish(harness.hooks, { type: "session.error", properties: { sessionID: name, error: { name, data: {} } } })
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: name, status: { type: "idle" } } })
      expect(harness.emitted.map((event) => event.event)).toEqual([expected])
    }
  })

  test("deprecated session.idle and unrelated events are ignored", async () => {
    const harness = createHarness()
    await publish(harness.hooks, { type: "session.idle", properties: { sessionID: "main" } })
    await publish(harness.hooks, { type: "message.updated", properties: {} })
    expect(harness.emitted).toHaveLength(0)
  })

  test("permission event and hook are deduplicated", async () => {
    const harness = createHarness()
    await publish(harness.hooks, { type: "permission.asked", properties: { sessionID: "main" } })
    await harness.hooks["permission.ask"]?.({ sessionID: "main" } as never, { status: "ask" })
    expect(harness.emitted.map((event) => event.event)).toEqual(["permission"])

    harness.setClock(2_000)
    await harness.hooks["permission.ask"]?.({ sessionID: "main" } as never, { status: "ask" })
    expect(harness.emitted.map((event) => event.event)).toEqual(["permission", "permission"])
  })

  test("permission requests from different sessions are not deduplicated", async () => {
    const harness = createHarness()
    await publish(harness.hooks, { type: "permission.asked", properties: { sessionID: "main" } })
    harness.setClock(1_500)
    await publish(harness.hooks, { type: "permission.asked", properties: { sessionID: "child" } })

    expect(harness.emitted.map((event) => event.event)).toEqual(["permission", "permission"])
  })

  test("question hook emits only for the question tool", async () => {
    const harness = createHarness()
    await harness.hooks["tool.execute.before"]?.(
      { tool: "question", sessionID: "main", callID: "call" },
      { args: {} },
    )
    await harness.hooks["tool.execute.before"]?.(
      { tool: "read", sessionID: "main", callID: "call-2" },
      { args: {} },
    )
    expect(harness.emitted.map((event) => event.event)).toEqual(["question"])
  })

  test("session deletion removes stored child metadata", async () => {
    const harness = createHarness()
    const info = { id: "child", title: "Deleted task", parentID: "main" }
    await publish(harness.hooks, { type: "session.created", properties: { info } })
    await publish(harness.hooks, { type: "session.deleted", properties: { info } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "busy" } } })
    harness.setClock(1_050)
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "idle" } } })
    expect(harness.emitted).toEqual([{ event: "complete", sessionTitle: null, durationMs: 50 }])
  })
})
