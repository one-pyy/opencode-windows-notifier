import type { SessionStatus } from "@opencode-ai/sdk"

export interface SessionState {
  title: string | null
  isChild: boolean | null
  active: boolean
  startedAtMs: number | null
}

export interface CompletionState {
  title: string | null
  isChild: boolean | null
  durationMs: number
}

const PERMISSION_DEDUPE_WINDOW_MS = 1_000

export class SessionTracker {
  readonly #sessions = new Map<string, SessionState>()
  readonly #lastPermissionAtBySession = new Map<string, number>()
  #lastPermissionAtWithoutSession = 0

  updateSession(sessionID: string, title: string | null, isChild: boolean): void {
    const current = this.#sessions.get(sessionID)
    this.#sessions.set(sessionID, {
      title,
      isChild,
      active: current?.active ?? false,
      startedAtMs: current?.startedAtMs ?? null,
    })
  }

  getSession(sessionID: string): SessionState | null {
    const state = this.#sessions.get(sessionID)
    return state ? { ...state } : null
  }

  updateStatus(sessionID: string, status: SessionStatus, nowMs: number): CompletionState | null {
    const state = this.#getOrCreate(sessionID)

    if (status.type === "busy" || status.type === "retry") {
      if (!state.active) {
        state.active = true
        state.startedAtMs = nowMs
      }
      return null
    }

    if (!state.active) {
      return null
    }

    const durationMs = Math.max(0, nowMs - (state.startedAtMs ?? nowMs))
    state.active = false
    state.startedAtMs = null
    return {
      title: state.title,
      isChild: state.isChild,
      durationMs,
    }
  }

  markError(sessionID: string): void {
    const state = this.#getOrCreate(sessionID)
    state.active = false
    state.startedAtMs = null
  }

  deleteSession(sessionID: string): void {
    this.#sessions.delete(sessionID)
    this.#lastPermissionAtBySession.delete(sessionID)
  }

  shouldSuppressPermission(sessionID: string | null, nowMs: number): boolean {
    const latestSeen = sessionID
      ? (this.#lastPermissionAtBySession.get(sessionID) ?? 0)
      : this.#lastPermissionAtWithoutSession
    if (latestSeen > 0 && nowMs - latestSeen < PERMISSION_DEDUPE_WINDOW_MS) {
      return true
    }

    if (sessionID) {
      this.#lastPermissionAtBySession.set(sessionID, nowMs)
    } else {
      this.#lastPermissionAtWithoutSession = nowMs
    }
    return false
  }

  #getOrCreate(sessionID: string): SessionState {
    const current = this.#sessions.get(sessionID)
    if (current) {
      return current
    }

    const state: SessionState = {
      title: null,
      isChild: null,
      active: false,
      startedAtMs: null,
    }
    this.#sessions.set(sessionID, state)
    return state
  }
}
