import { describe, expect, test } from "bun:test"
import { SessionTracker } from "../src/state"

describe("SessionTracker", () => {
  test("idle without activity does not complete", () => {
    const tracker = new SessionTracker()
    expect(tracker.updateStatus("session", { type: "idle" }, 100)).toBeNull()
  })

  test("busy and retry form one activity window", () => {
    const tracker = new SessionTracker()
    tracker.updateStatus("session", { type: "busy" }, 100)
    tracker.updateStatus("session", { type: "retry", attempt: 1, message: "retry", next: 200 }, 150)
    tracker.updateStatus("session", { type: "busy" }, 200)

    expect(tracker.updateStatus("session", { type: "idle" }, 350)).toEqual({
      title: null,
      isChild: null,
      durationMs: 250,
    })
    expect(tracker.updateStatus("session", { type: "idle" }, 400)).toBeNull()
  })

  test("an error closes the active window", () => {
    const tracker = new SessionTracker()
    tracker.updateStatus("session", { type: "busy" }, 100)
    tracker.markError("session")
    expect(tracker.updateStatus("session", { type: "idle" }, 200)).toBeNull()
  })

  test("separate activity windows complete separately", () => {
    const tracker = new SessionTracker()
    tracker.updateStatus("session", { type: "busy" }, 100)
    expect(tracker.updateStatus("session", { type: "idle" }, 150)?.durationMs).toBe(50)
    tracker.updateStatus("session", { type: "busy" }, 300)
    expect(tracker.updateStatus("session", { type: "idle" }, 375)?.durationMs).toBe(75)
  })

  test("session metadata survives activity transitions and is deleted explicitly", () => {
    const tracker = new SessionTracker()
    tracker.updateSession("child", "Review task", true)
    tracker.updateStatus("child", { type: "busy" }, 100)
    expect(tracker.updateStatus("child", { type: "idle" }, 200)).toEqual({
      title: "Review task",
      isChild: true,
      durationMs: 100,
    })
    tracker.deleteSession("child")
    expect(tracker.getSession("child")).toBeNull()
  })

  test("permission signals are deduplicated only within the same session", () => {
    const tracker = new SessionTracker()
    expect(tracker.shouldSuppressPermission("session", 1_000)).toBeFalse()
    expect(tracker.shouldSuppressPermission("session", 1_500)).toBeTrue()
    expect(tracker.shouldSuppressPermission("other", 1_500)).toBeFalse()
    expect(tracker.shouldSuppressPermission(null, 1_600)).toBeFalse()
    expect(tracker.shouldSuppressPermission(null, 1_700)).toBeTrue()
    expect(tracker.shouldSuppressPermission("session", 2_000)).toBeFalse()
  })
})
