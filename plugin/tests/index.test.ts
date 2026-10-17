import { describe, expect, test } from "bun:test"
import type { Event, SessionStatus } from "@opencode-ai/sdk"
import type { Hooks, PluginInput } from "@opencode-ai/plugin"
import * as pluginModule from "../src/index"
import { createEventHooks, type EventHookScheduler, type LogicalEvent } from "../src/hooks"

type TailMessage = { info?: { id?: string; role?: string } }

function createHarness(
  sessions: Record<string, { title: string; parentID?: string }> = {},
  initialTail: TailMessage[] = [],
) {
  const emitted: LogicalEvent[] = []
  const logs: Array<{ message: string; extra: Record<string, unknown> }> = []
  let clock = 1_000
  let tail = initialTail
  let messagesShouldFail = false
  let statuses: Record<string, SessionStatus> = {}
  let childQueryFailure: "children" | "status" | undefined
  const childrenQueries: string[] = []
  const timers = new Map<number, { callback: () => void | Promise<void>; delayMs: number }>()
  let nextTimerId = 0

  const client = {
    session: {
      get: async ({ path }: { path: { id: string } }) => ({ data: sessions[path.id] }),
      children: async ({ path }: { path: { id: string } }) => {
        childrenQueries.push(path.id)
        if (childQueryFailure === "children") throw new Error("children unavailable")
        return { data: Object.entries(sessions).filter(([, session]) => session.parentID === path.id).map(([id, session]) => ({ id, ...session })) }
      },
      status: async () => {
        if (childQueryFailure === "status") throw new Error("status unavailable")
        return { data: statuses }
      },
      messages: async () => {
        if (messagesShouldFail) {
          throw new Error("session messages unavailable")
        }
        return { data: tail }
      },
    },
  } as unknown as PluginInput["client"]

  const scheduler: EventHookScheduler = {
    setTimeout(callback, delayMs) {
      const id = nextTimerId++
      timers.set(id, { callback, delayMs })
      return id
    },
    clearTimeout(handle) {
      timers.delete(handle as number)
    },
  }

  const hooks = createEventHooks(client, (event) => emitted.push(event), {
    now: () => clock,
    scheduler,
    delayMs: 8_000,
    log: (message, extra) => { logs.push({ message, extra }) },
  })

  return {
    emitted,
    logs,
    hooks,
    childrenQueries,
    setStatuses(value: Record<string, SessionStatus>) {
      statuses = value
    },
    failChildQuery(query: "children" | "status") {
      childQueryFailure = query
    },
    setClock(value: number) {
      clock = value
    },
    setTail(next: TailMessage[]) {
      tail = next
    },
    failMessages() {
      messagesShouldFail = true
    },
    pendingDelays() {
      return [...timers.values()].map((timer) => timer.delayMs)
    },
    async runTimers() {
      const pending = [...timers.entries()]
      timers.clear()
      for (const [, timer] of pending) {
        await timer.callback()
      }
    },
  }
}

async function publish(hooks: Pick<Hooks, "event">, event: unknown): Promise<void> {
  await hooks.event?.({ event: event as Event })
}

describe("OpenCode event mapping", () => {
  test("plugin entry exposes exactly one runtime function", () => {
    expect(Object.values(pluginModule).filter((value) => typeof value === "function")).toHaveLength(1)
  })

  test("busy to idle emits one main completion", async () => {
    const harness = createHarness()
    await publish(harness.hooks, { type: "session.created", properties: { info: { id: "main", title: "Build feature" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    harness.setClock(1_250)
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
    await harness.runTimers()

    expect(harness.emitted).toEqual([{ event: "complete", sessionTitle: "Build feature", durationMs: 250 }])
  })

  test("unknown metadata is refreshed before child completion", async () => {
    const harness = createHarness({ child: { title: "Inspect types", parentID: "main" } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "busy" } } })
    harness.setClock(1_100)
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "idle" } } })
    await harness.runTimers()

    expect(harness.emitted).toEqual([{ event: "subagent_complete", sessionTitle: "Inspect types", durationMs: 100 }])
  })

  test("an unchanged tail delivers the error after the delay", async () => {
    const harness = createHarness({ main: { title: "Build feature" } }, [{ info: { id: "msg-error", role: "assistant" } }])
    await publish(harness.hooks, { type: "session.created", properties: { info: { id: "main", title: "Build feature" } } })
    await publish(harness.hooks, { type: "session.error", properties: { sessionID: "main", error: { name: "UnknownError", data: {} } } })

    expect(harness.emitted).toEqual([])
    expect(harness.pendingDelays()).toEqual([8_000])

    await harness.runTimers()
    expect(harness.emitted).toEqual([{ event: "error", sessionTitle: "Build feature", durationMs: null }])
  })

  test("a resumed tail drops the delayed error", async () => {
    const harness = createHarness({ main: { title: "Build feature" } }, [{ info: { id: "msg-error", role: "assistant" } }])
    await publish(harness.hooks, { type: "session.error", properties: { sessionID: "main", error: { name: "UnknownError", data: {} } } })

    harness.setTail([
      { info: { id: "msg-error", role: "assistant" } },
      { info: { id: "msg-recovery", role: "user" } },
    ])
    await harness.runTimers()

    expect(harness.emitted).toEqual([])
  })

  test("an unverifiable tail delivers the error immediately", async () => {
    const harness = createHarness({ main: { title: "Build feature" } })
    harness.failMessages()
    await publish(harness.hooks, { type: "session.created", properties: { info: { id: "main", title: "Build feature" } } })
    await publish(harness.hooks, { type: "session.error", properties: { sessionID: "main", error: { name: "UnknownError", data: {} } } })

    expect(harness.emitted).toEqual([{ event: "error", sessionTitle: "Build feature", durationMs: null }])
  })

  test("a later error replaces the pending delayed error", async () => {
    const harness = createHarness({ main: { title: "Build feature" } }, [{ info: { id: "msg-error", role: "assistant" } }])
    await publish(harness.hooks, { type: "session.error", properties: { sessionID: "main", error: { name: "UnknownError", data: {} } } })
    await publish(harness.hooks, { type: "session.error", properties: { sessionID: "main", error: { name: "UnknownError", data: {} } } })

    expect(harness.pendingDelays()).toEqual([8_000])
    await harness.runTimers()
    expect(harness.emitted).toHaveLength(1)
    expect(harness.emitted[0]?.event).toBe("error")
  })

  test("error and both abort names suppress later completion", async () => {
    for (const [name, expected] of [
      ["UnknownError", "error"],
      ["MessageAbortedError", "cancelled"],
      ["AbortError", "cancelled"],
    ] as const) {
      const harness = createHarness()
      harness.setTail([{ info: { id: "msg-error", role: "assistant" } }])
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: name, status: { type: "busy" } } })
      await publish(harness.hooks, { type: "session.error", properties: { sessionID: name, error: { name, data: {} } } })
      await harness.runTimers()
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: name, status: { type: "idle" } } })
      expect(harness.emitted.map((event) => event.event)).toEqual([expected])
    }
  })

  test("delayed error stays pending across a bare idle", async () => {
    const harness = createHarness({ main: { title: "Build feature" } }, [{ info: { id: "msg-error", role: "assistant" } }])
    await publish(harness.hooks, { type: "session.created", properties: { info: { id: "main", title: "Build feature" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    await publish(harness.hooks, { type: "session.error", properties: { sessionID: "main", error: { name: "UnknownError", data: {} } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })

    expect(harness.emitted).toEqual([])
    await harness.runTimers()
    expect(harness.emitted).toEqual([{ event: "error", sessionTitle: "Build feature", durationMs: null }])
  })

  test("a completion is delayed and delivered when the tail is unchanged", async () => {
    const harness = createHarness({}, [{ info: { id: "msg-done", role: "assistant" } }])
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    harness.setClock(1_500)
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })

    expect(harness.emitted).toEqual([])
    await harness.runTimers()
    expect(harness.emitted).toEqual([{ event: "complete", sessionTitle: null, durationMs: 500 }])
  })

  test("a completion is dropped when auto-continue resumes the session", async () => {
    const harness = createHarness({}, [{ info: { id: "msg-done", role: "assistant" } }])
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    harness.setClock(1_500)
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })

    harness.setTail([
      { info: { id: "msg-done", role: "assistant" } },
      { info: { id: "msg-recovery", role: "user" } },
    ])
    await harness.runTimers()

    expect(harness.emitted).toEqual([])
  })

  test("busy and retry children drop main completion before the delay", async () => {
    for (const status of [{ type: "busy" }, { type: "retry", attempt: 1, message: "Retrying", next: 2_000 }] satisfies SessionStatus[]) {
      const harness = createHarness({ child: { title: "Inspect", parentID: "main" } }, [{ info: { id: "msg-done" } }])
      harness.setStatuses({ child: status })
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })

      expect(harness.childrenQueries).toEqual(["main"])
      expect(harness.pendingDelays()).toEqual([])
      expect(harness.logs).toContainEqual({ message: "notification.skipped", extra: { sessionID: "main", event: "complete", reason: "busy_children" } })
      expect(harness.logs).toContainEqual({ message: "children.checked", extra: { sessionID: "main", childCount: 1, busyChildren: [{ sessionID: "child", status: status.type }] } })
      harness.setStatuses({})
      await harness.runTimers()
      expect(harness.emitted).toEqual([])
    }
  })

  test("idle children and unrelated busy sessions preserve the delayed completion", async () => {
    for (const childStatus of [undefined, { type: "idle" }] satisfies (SessionStatus | undefined)[]) {
      const harness = createHarness({ child: { title: "Inspect", parentID: "main" } }, [{ info: { id: "msg-done" } }])
      harness.setStatuses({ unrelated: { type: "busy" }, ...(childStatus ? { child: childStatus } : {}) })
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })

      expect(harness.emitted).toEqual([])
      expect(harness.pendingDelays()).toEqual([8_000])
      await harness.runTimers()
      expect(harness.emitted.map((event) => event.event)).toEqual(["complete"])
    }
  })

  test("child query failures preserve the delayed main completion", async () => {
    for (const query of ["children", "status"] as const) {
      const harness = createHarness({ child: { title: "Inspect", parentID: "main" } }, [{ info: { id: "msg-done" } }])
      harness.failChildQuery(query)
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
      await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
      expect(harness.pendingDelays()).toEqual([8_000])
      await harness.runTimers()
      expect(harness.emitted.map((event) => event.event)).toEqual(["complete"])
    }
  })

  test("busy children suppress completion even when the tail is unavailable", async () => {
    const harness = createHarness({ child: { title: "Inspect", parentID: "main" } })
    harness.setStatuses({ child: { type: "busy" } })
    harness.failMessages()
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
    expect(harness.emitted).toEqual([])
  })

  test("child completion and errors do not query child activity", async () => {
    const harness = createHarness({ child: { title: "Inspect", parentID: "main" } }, [{ info: { id: "msg-done" } }])
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "busy" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "child", status: { type: "idle" } } })
    await publish(harness.hooks, { type: "session.error", properties: { sessionID: "main", error: { name: "UnknownError", data: {} } } })
    await harness.runTimers()
    expect(harness.childrenQueries).toEqual([])
    expect(harness.emitted.map((event) => event.event)).toEqual(["subagent_complete", "error"])
  })

  test("diagnostics distinguish inactive idle, scheduling, tail changes and emission", async () => {
    const harness = createHarness({}, [{ info: { id: "first" } }])
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
    expect(harness.logs).toContainEqual({ message: "notification.skipped", extra: { sessionID: "main", event: "complete", reason: "no_active_transition" } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
    expect(harness.logs).toContainEqual({ message: "notification.scheduled", extra: { sessionID: "main", event: "complete", delayMs: 8_000, tailMessageId: "first" } })
    harness.setTail([{ info: { id: "second" } }])
    await harness.runTimers()
    expect(harness.logs).toContainEqual({ message: "notification.skipped", extra: { sessionID: "main", event: "complete", reason: "tail_changed", tailMessageId: "first", currentTailId: "second" } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } })
    await publish(harness.hooks, { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } })
    await harness.runTimers()
    expect(harness.logs).toContainEqual({ message: "notification.emit", extra: { sessionID: "main", event: "complete" } })
    expect(harness.emitted).toHaveLength(1)
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
    await harness.runTimers()
    expect(harness.emitted).toEqual([{ event: "complete", sessionTitle: null, durationMs: 50 }])
  })
})
