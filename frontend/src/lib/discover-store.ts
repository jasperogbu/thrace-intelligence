import { useSyncExternalStore } from "react"
import {
  clearDiscoverScan,
  DISCOVER_MAX_IDEAS,
  fetchDiscoverScan,
  saveDiscoverScan,
  streamDiscover,
  type DiscoverIdea,
  type StreamEvent,
  type User,
} from "@/lib/api"

/**
 * Discover scan state lives at module level so it survives view switches
 * (navigating away and back mid-scan keeps the scan running) and is synced
 * to the signed-in user's account, surviving logout/login until cleared.
 */
interface DiscoverState {
  focus: string
  scanning: boolean
  log: string
  ideas: DiscoverIdea[]
  error: string | null
  hydratedFor: string | null
}

let state: DiscoverState = {
  focus: "",
  scanning: false,
  log: "",
  ideas: [],
  error: null,
  hydratedFor: null,
}

const listeners = new Set<() => void>()

function set(patch: Partial<DiscoverState>) {
  state = { ...state, ...patch }
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useDiscover(): DiscoverState {
  return useSyncExternalStore(subscribe, () => state)
}

/** Load the user's persisted scan once per account (and after re-login). */
export async function hydrateDiscover(user: User | null): Promise<void> {
  if (!user || state.hydratedFor === user.id) return
  set({ hydratedFor: user.id })
  if (state.scanning) return // never clobber an in-flight scan
  const scan = await fetchDiscoverScan()
  if (scan && (scan.log || scan.ideas.length > 0)) {
    set({
      focus: scan.focus,
      log: scan.log,
      ideas: scan.ideas.slice(0, DISCOVER_MAX_IDEAS),
      error: null,
    })
  } else {
    // Server is authoritative on hydration — show a clean slate.
    set({ focus: "", log: "", ideas: [], error: null })
  }
}

/** Forget the hydration marker so the next visit re-syncs from the server. */
export function resetDiscoverHydration() {
  set({ hydratedFor: null })
}

export function setDiscoverFocus(focus: string) {
  set({ focus })
}

/** Clear the previous scan, locally and on the server. */
export function clearDiscover() {
  set({ log: "", ideas: [], error: null, focus: "" })
  void clearDiscoverScan()
}

/** Start a new scan; deltas continue into module state across navigation. */
export function startDiscoverScan() {
  if (state.scanning) return
  const focus = state.focus.trim()
  set({ scanning: true, log: "", ideas: [], error: null })

  const onEvent = (ev: StreamEvent) => {
    switch (ev.type) {
      case "delta":
        set({ log: state.log + ev.data })
        break
      case "idea":
        // The backend caps a scan at DISCOVER_MAX_IDEAS; guard here too so a
        // duplicated or retried stream can't grow the list or the saved scan.
        if (state.ideas.length >= DISCOVER_MAX_IDEAS) break
        set({
          ideas: [
            ...state.ideas,
            { title: ev.title, prompt: ev.prompt, rationale: ev.rationale },
          ],
        })
        break
      case "error":
        set({ error: ev.message })
        break
      case "status":
      case "done":
      case "reset":
      case "stage_start":
      case "stage_done":
        break
    }
  }

  streamDiscover(focus, onEvent)
    .catch((err: unknown) => {
      set({ error: err instanceof Error ? err.message : String(err) })
    })
    .finally(() => {
      set({ scanning: false })
      // Persist the completed scan to the account.
      if (state.log || state.ideas.length > 0) {
        void saveDiscoverScan({
          focus,
          log: state.log,
          ideas: state.ideas,
        })
      }
    })
}
