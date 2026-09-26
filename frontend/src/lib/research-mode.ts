import { useSyncExternalStore } from "react"

/**
 * How reports are produced.
 *
 * Instant (the default) writes the whole report in one streaming model call —
 * no tools, no research stages. Deep runs the full research pipeline, which
 * searches the web but costs many model requests per report, so it is opt-in.
 *
 * Persisted so the choice survives a reload. Read at stream time by
 * `use-analyze`, so it applies to whatever run is started next.
 */
const STORAGE_KEY = "thrace_deep_research"

function load(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1"
  } catch {
    return false
  }
}

let deep = load()
const listeners = new Set<() => void>()

export function isDeepResearch(): boolean {
  return deep
}

export function setDeepResearch(next: boolean): void {
  if (next === deep) return
  deep = next
  try {
    localStorage.setItem(STORAGE_KEY, next ? "1" : "0")
  } catch {
    // ignore persistence failures
  }
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useDeepResearch(): boolean {
  return useSyncExternalStore(subscribe, isDeepResearch)
}
