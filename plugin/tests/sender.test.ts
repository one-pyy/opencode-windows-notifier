import { afterEach, describe, expect, mock, test } from "bun:test"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import type { PluginConfig } from "../src/config"
import { createEventHooks } from "../src/hooks"
import {
  buildEventPayload,
  sendEvent,
  type EventPayload,
} from "../src/sender"

const config: PluginConfig = {
  serverUrl: "http://127.0.0.1:8765",
  token: "shared-secret",
  timeoutMs: 100,
  delayMs: 8_000,
}

const payload: EventPayload = buildEventPayload(
  { event: "complete", sessionTitle: "Implement notifier", durationMs: 18_342 },
  "opencode",
  new Date("2026-07-17T00:00:00.000Z"),
)

const originalFetch = globalThis.fetch
const originalWarn = console.warn
function installFetch(
  implementation: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): void {
  globalThis.fetch = implementation as unknown as typeof fetch
}

afterEach(() => {
  globalThis.fetch = originalFetch
  console.warn = originalWarn
})

async function settle(): Promise<void> {
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 20))
}

describe("event payload", () => {
  test("matches the shared protocol sample", () => {
    const sample = JSON.parse(readFileSync(resolve(import.meta.dir, "../../protocol/event-v1.example.json"), "utf8"))
    expect(payload).toEqual(sample)
  })
})

describe("HTTP sender", () => {
  test("diagnostics correlate delivery results without exposing secrets or payload text", async () => {
    for (const result of ["accepted", "http_error", "network_error", "timeout"] as const) {
      const logs: Array<{ message: string; extra: Record<string, unknown> }> = []
      installFetch(mock(async (_input, init) => {
        if (result === "network_error") throw new Error(config.token + payload.message)
        if (result === "timeout") {
          return new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new Error(config.token)))
          })
        }
        return new Response(null, { status: result === "accepted" ? 204 : 503 })
      }))
      expect(sendEvent({ ...config, timeoutMs: 10 }, payload, {
        sessionID: "main",
        log: (message, extra) => { logs.push({ message, extra }) },
      })).toBeUndefined()
      await settle()
      expect(logs.map((entry) => entry.message)).toEqual(["delivery.started", "delivery.finished"])
      expect(logs[1]?.extra).toMatchObject({ sessionID: "main", event: "complete", result })
      if (result === "accepted" || result === "http_error") {
        expect(logs[1]?.extra.status).toBe(result === "accepted" ? 204 : 503)
      }
      const serialized = JSON.stringify(logs)
      expect(serialized).not.toContain(config.token)
      expect(serialized).not.toContain(payload.message)
      expect(serialized).not.toContain(payload.session_title!)
      expect(serialized).not.toContain(config.serverUrl)
    }
  })

  test("posts the minimal payload with bearer authentication", async () => {
    const requests: Array<{ input: string | URL | Request; init?: RequestInit }> = []
    installFetch(mock(async (input, init) => {
      requests.push({ input, init })
      return new Response(null, { status: 204 })
    }))

    expect(sendEvent(config, payload)).toBeUndefined()
    await settle()

    expect(requests).toHaveLength(1)
    expect(String(requests[0]?.input)).toBe("http://127.0.0.1:8765/v1/events")
    expect(requests[0]?.init?.method).toBe("POST")
    expect(requests[0]?.init?.headers).toEqual({
      Authorization: "Bearer shared-secret",
      "Content-Type": "application/json",
    })
    expect(JSON.parse(String(requests[0]?.init?.body))).toEqual(payload)
  })

  test("timeout aborts once without retrying or warning", async () => {
    let calls = 0
    installFetch(mock((_input, init) => {
      calls += 1
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))
      })
    }))
    const warn = mock((_message: string) => undefined)
    console.warn = warn

    sendEvent({ ...config, timeoutMs: 10 }, payload)
    await settle()
    expect(calls).toBe(1)
    expect(warn).toHaveBeenCalledTimes(0)
  })

  test("connection failures and non-2xx responses stay silent without retrying", async () => {
    const warn = mock((_message: string) => undefined)
    console.warn = warn
    let calls = 0
    installFetch(mock(async () => {
      calls += 1
      throw new Error("connection refused")
    }))
    sendEvent(config, payload)
    await settle()

    installFetch(mock(async () => {
      calls += 1
      return new Response(null, { status: 503 })
    }))
    sendEvent(config, payload)
    await settle()

    expect(calls).toBe(2)
    expect(warn).toHaveBeenCalledTimes(0)
  })

  test("hook completion does not wait for the HTTP request", async () => {
    let releaseRequest: (() => void) | undefined
    installFetch(mock((_input, init) => new Promise<Response>((resolveResponse, reject) => {
      releaseRequest = () => resolveResponse(new Response(null, { status: 204 }))
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))
    })))

    const client = {
      session: {
        get: async () => ({ data: null }),
        messages: async () => ({ data: [{ info: { id: "msg-done", role: "assistant" } }] }),
      },
    } as never
    const timers: Array<() => void | Promise<void>> = []
    const scheduler = {
      setTimeout(callback: () => void | Promise<void>) {
        timers.push(callback)
        return timers.length
      },
      clearTimeout() {},
    }
    const hooks = createEventHooks(
      client,
      (event) => sendEvent(config, buildEventPayload(event, "opencode")),
      { now: () => 1_000, scheduler },
    )
    await hooks.event?.({ event: { type: "session.status", properties: { sessionID: "main", status: { type: "busy" } } } as never })
    const hookResult = hooks.event?.({ event: { type: "session.status", properties: { sessionID: "main", status: { type: "idle" } } } as never })

    await expect(hookResult).resolves.toBeUndefined()
    expect(releaseRequest).toBeUndefined()

    await timers[0]?.()
    expect(releaseRequest).toBeDefined()
    releaseRequest?.()
    await settle()
  })
})
