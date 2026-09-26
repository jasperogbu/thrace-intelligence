import { useCallback, useEffect, useRef, useState } from "react"
import {
  addWatch,
  fetchUpdates,
  getWatchlist,
  removeWatch,
  setServerChatPin,
  streamAnalysis,
  streamAsk,
  streamVenture,
  syncExchange,
  VENTURE_STAGES,
  type RunMode,
  type StreamEvent,
} from "@/lib/api"
import { isDeepResearch } from "@/lib/research-mode"

export interface StageState {
  id: string
  label: string
  status: "pending" | "active" | "done"
  detail?: string
}

/** One request/response turn inside a chat. */
export interface Exchange {
  id: string
  query: string
  mode: RunMode
  content: string
  status: "running" | "done" | "error"
  statusLabel: string
  statusDetail: string
  stages: StageState[]
  reportStatus: "pending" | "active" | "done"
  timestamp: number
  error?: string
}

/**
 * A chat. `exchanges` is the full conversation; the top-level fields mirror
 * the latest exchange (title stays the first query) so history/library
 * components keep working unchanged.
 */
export interface Run {
  id: string
  query: string
  mode: RunMode
  status: "running" | "done" | "error"
  content: string
  statusLabel: string
  statusDetail: string
  stages: StageState[]
  reportStatus: "pending" | "active" | "done"
  timestamp: number
  pinned?: boolean
  error?: string
  exchanges: Exchange[]
}

const STORAGE_KEY = "thrace_runs_v1"
/** Pre-rename key — read once as a fallback so existing local history survives. */
const LEGACY_STORAGE_KEY = "jaspa_runs_v1"
const MAX_PERSISTED = 60
const POLL_INTERVAL = 30_000
const MODES: RunMode[] = [
  "venture",
  "ask",
  "monitor",
  "digest",
  "competitor",
  "sentiment",
  "metrics",
]

const initialStages = (): StageState[] =>
  VENTURE_STAGES.map((s) => ({ ...s, status: "pending" }))

function mirrorLatest(run: Run): Run {
  const last = run.exchanges[run.exchanges.length - 1]
  if (!last) return run
  return {
    ...run,
    // The chat badge reflects its nature (first exchange); turn-level modes
    // (ask/monitor/digest) display per exchange.
    mode: run.exchanges[0].mode,
    status: last.status,
    content: last.content,
    statusLabel: last.statusLabel,
    statusDetail: last.statusDetail,
    stages: last.stages,
    reportStatus: last.reportStatus,
    error: last.error,
  }
}

function sanitizeExchange(raw: Record<string, unknown>): Exchange | null {
  if (typeof raw.query !== "string" || !raw.query.trim()) return null
  const mode = MODES.includes(raw.mode as RunMode) ? (raw.mode as RunMode) : "competitor"
  const wasRunning = raw.status === "running"
  return {
    id: typeof raw.id === "string" && raw.id ? raw.id : crypto.randomUUID(),
    query: raw.query,
    mode,
    content: typeof raw.content === "string" ? raw.content : "",
    status: wasRunning ? "error" : raw.status === "error" ? "error" : "done",
    statusLabel: typeof raw.statusLabel === "string" ? raw.statusLabel : "",
    statusDetail: typeof raw.statusDetail === "string" ? raw.statusDetail : "",
    stages: Array.isArray(raw.stages)
      ? (raw.stages as StageState[])
          .filter((s) => s && typeof (s as StageState).id === "string")
          .map((s) => ({ ...s }))
      : [],
    reportStatus: raw.reportStatus === "active" ? "active" : "done",
    timestamp: typeof raw.timestamp === "number" ? raw.timestamp : Date.now(),
    error: wasRunning
      ? "Run interrupted by page reload"
      : typeof raw.error === "string"
        ? raw.error
        : undefined,
  }
}

function sanitizeRun(raw: Record<string, unknown>): Run | null {
  if (typeof raw.id !== "string" || typeof raw.query !== "string") return null
  const exchanges: Exchange[] = []
  if (Array.isArray(raw.exchanges)) {
    for (const e of raw.exchanges) {
      if (e && typeof e === "object") {
        const ex = sanitizeExchange(e as Record<string, unknown>)
        if (ex) exchanges.push(ex)
      }
    }
  }
  if (exchanges.length === 0) {
    // legacy persisted run — a single exchange stored at the top level
    const ex = sanitizeExchange(raw)
    if (!ex) return null
    exchanges.push(ex)
  }
  const base: Run = {
    id: raw.id,
    query: raw.query,
    mode: exchanges[0].mode,
    status: exchanges[exchanges.length - 1].status,
    content: "",
    statusLabel: "",
    statusDetail: "",
    stages: [],
    reportStatus: "done",
    timestamp: typeof raw.timestamp === "number" ? raw.timestamp : Date.now(),
    pinned: raw.pinned === true,
    error: undefined,
    exchanges,
  }
  return mirrorLatest(base)
}

function sanitizeRuns(raw: unknown): Run[] {
  if (!Array.isArray(raw)) return []
  const out: Run[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const run = sanitizeRun(item as Record<string, unknown>)
    if (run) out.push(run)
  }
  return out
}

function loadPersisted(): { runs: Run[]; activeId: string | null } | null {
  try {
    let raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) raw = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { runs?: unknown; activeId?: unknown }
    return {
      runs: sanitizeRuns(parsed.runs),
      activeId: typeof parsed.activeId === "string" ? parsed.activeId : null,
    }
  } catch {
    return null
  }
}

export function useAnalyze() {
  const [initial] = useState(loadPersisted)
  const [runs, setRuns] = useState<Run[]>(initial?.runs ?? [])
  const [activeId, setActiveId] = useState<string | null>(initial?.activeId ?? null)
  const [watchedIds, setWatchedIds] = useState<Set<string>>(new Set())
  const abortRef = useRef<AbortController | null>(null)
  const runsRef = useRef<Run[]>(initial?.runs ?? [])
  const lastPollRef = useRef<number>(0)
  if (lastPollRef.current === 0) {
    lastPollRef.current = Math.floor(Date.now() / 1000)
  }

  useEffect(() => {
    runsRef.current = runs
  }, [runs])

  const activeRun = runs.find((r) => r.id === activeId) ?? null

  // Persist history (debounced so streaming deltas don't thrash storage).
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ runs: runs.slice(0, MAX_PERSISTED), activeId }),
        )
      } catch {
        // storage quota exceeded — keep session-only
      }
    }, 600)
    return () => clearTimeout(t)
  }, [runs, activeId])

  // Load watchlist from the server once.
  useEffect(() => {
    getWatchlist().then((items) => {
      setWatchedIds(new Set(items.map((i) => i.run_id)))
    })
  }, [])

  // Poll for autonomous updates (monitoring re-validations + digests) and
  // merge them into the local chats.
  useEffect(() => {
    const timer = setInterval(async () => {
      if (document.visibilityState !== "visible") return
      const updates = await fetchUpdates(lastPollRef.current)
      lastPollRef.current = Math.floor(Date.now() / 1000)
      if (updates.length === 0) return
      setRuns((rs) => {
        let next = rs
        for (const upd of updates) {
          const localIdx = next.findIndex((r) => r.id === upd.id)
          const newExchanges: Exchange[] = upd.exchanges.map((e) => ({
            id: e.id,
            query: e.query ?? "Thrace update",
            mode: (e.mode as RunMode) ?? "monitor",
            content: e.content ?? "",
            status: "done",
            statusLabel: "",
            statusDetail: "",
            stages: [],
            reportStatus: "done",
            timestamp: e.created_at * 1000,
          }))
          if (localIdx === -1) {
            const run: Run = {
              id: upd.id,
              query: upd.query,
              mode: (upd.mode as RunMode) ?? "monitor",
              status: "done",
              content: newExchanges[0]?.content ?? "",
              statusLabel: "",
              statusDetail: "",
              stages: [],
              reportStatus: "done",
              timestamp: upd.created_at * 1000,
              exchanges: newExchanges,
            }
            next = [run, ...next]
          } else {
            next = next.map((r) => {
              if (r.id !== upd.id) return r
              const known = new Set(r.exchanges.map((e) => e.id))
              const merged = [...r.exchanges, ...newExchanges.filter((e) => !known.has(e.id))]
              merged.sort((a, b) => a.timestamp - b.timestamp)
              return mirrorLatest({ ...r, exchanges: merged })
            })
          }
        }
        return next
      })
    }, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [])

  const toggleWatch = useCallback((id: string) => {
    const run = runsRef.current.find((r) => r.id === id)
    setWatchedIds((cur) => {
      const isWatched = cur.has(id)
      if (isWatched) {
        void removeWatch(id)
      } else if (run) {
        void addWatch(id, run.query, run.exchanges[0]?.mode ?? run.mode)
      }
      const nextSet = new Set(cur)
      if (isWatched) nextSet.delete(id)
      else nextSet.add(id)
      return nextSet
    })
  }, [])

  /**
   * Replace local history with the signed-in user's server-side chats,
   * merging anything already stored locally. Called once after login.
   */
  const loadServerChats = useCallback(
    (chats: {
      id: string
      query: string
      mode: string
      pinned: number
      created_at: number
      exchanges: {
        id: string
        query: string | null
        mode: string | null
        content: string | null
        kind: string
        created_at: number
      }[]
    }[]) => {
      setRuns((rs) => {
        const byId = new Map(rs.map((r) => [r.id, r]))
        for (const chat of chats) {
          const serverPinned = chat.pinned === 1
          const local = byId.get(chat.id)
          if (local) {
            // Local content is at least as fresh; pins come from the server
            // (they are persisted the instant they are toggled).
            byId.set(chat.id, { ...local, pinned: serverPinned })
            continue
          }
          const exchanges: Exchange[] = chat.exchanges.map((e) => ({
            id: e.id,
            query: e.query ?? "Thrace update",
            mode: (e.mode as RunMode) ?? "monitor",
            content: e.content ?? "",
            status: "done",
            statusLabel: "",
            statusDetail: "",
            stages: [],
            reportStatus: "done",
            timestamp: e.created_at * 1000,
          }))
          if (exchanges.length === 0) continue
          byId.set(chat.id, {
            id: chat.id,
            query: chat.query,
            mode: (chat.mode as RunMode) ?? "venture",
            status: "done",
            content: exchanges[exchanges.length - 1].content,
            statusLabel: "",
            statusDetail: "",
            stages: [],
            reportStatus: "done",
            timestamp: chat.created_at * 1000,
            pinned: serverPinned,
            exchanges,
          })
        }
        return Array.from(byId.values()).sort((a, b) => b.timestamp - a.timestamp)
      })
    },
    [],
  )

  /**
   * Start a new chat, or — when `appendToId` references an open, idle chat —
   * append the query as the next turn of that conversation.
   */
  const startRun = useCallback((query: string, mode: RunMode, appendToId?: string) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const makeExchange = (q: string, m: RunMode): Exchange => ({
      id: crypto.randomUUID(),
      query: q,
      mode: m,
      content: "",
      status: "running",
      statusLabel: m === "venture" ? "Running venture pipeline" : "Searching the web",
      statusDetail:
        m === "venture"
          ? `Thrace agents are validating: ${q}…`
          : `Scanning live sources for ${q}…`,
      stages: m === "venture" ? initialStages() : [],
      reportStatus: "pending",
      timestamp: Date.now(),
    })

    const target = appendToId
      ? runsRef.current.find((r) => r.id === appendToId && r.status !== "running")
      : undefined

    let runId: string
    let exIdx: number

    if (target) {
      // continue the existing conversation
      runId = target.id
      exIdx = target.exchanges.length
      const ex = makeExchange(query, mode)
      setRuns((rs) =>
        rs.map((r) =>
          r.id === runId
            ? mirrorLatest({ ...r, exchanges: [...r.exchanges, ex] })
            : r,
        ),
      )
    } else {
      runId = crypto.randomUUID()
      exIdx = 0
      const run: Run = {
        id: runId,
        query,
        mode,
        status: "running",
        content: "",
        statusLabel: "",
        statusDetail: "",
        stages: mode === "venture" ? initialStages() : [],
        reportStatus: "pending",
        timestamp: Date.now(),
        exchanges: [makeExchange(query, mode)],
      }
      setRuns((rs) => [mirrorLatest(run), ...rs])
      setActiveId(runId)
    }

    const patchExchange = (patch: Partial<Exchange>) => {
      setRuns((rs) =>
        rs.map((r) => {
          if (r.id !== runId) return r
          const exchanges = r.exchanges.map((e, i) =>
            i === exIdx ? { ...e, ...patch } : e,
          )
          return mirrorLatest({ ...r, exchanges })
        }),
      )
    }

    const patchStages = (update: (stages: StageState[]) => StageState[]) => {
      setRuns((rs) =>
        rs.map((r) => {
          if (r.id !== runId) return r
          const exchanges = r.exchanges.map((e, i) =>
            i === exIdx ? { ...e, stages: update(e.stages) } : e,
          )
          return mirrorLatest({ ...r, exchanges })
        }),
      )
    }

    let acc = ""

    const onEvent = (ev: StreamEvent) => {
      switch (ev.type) {
        case "status":
          patchExchange({ statusLabel: ev.label, statusDetail: ev.detail })
          break
        case "stage_start":
          if (ev.stage === "report") {
            patchExchange({
              statusLabel: "Synthesising report",
              statusDetail: "Lead analyst assembling the report…",
              reportStatus: "active",
            })
          } else {
            patchExchange({
              statusLabel: ev.label ?? ev.stage,
              statusDetail: ev.detail ?? "",
            })
          }
          patchStages((stages) =>
            stages.map((s) =>
              s.id === ev.stage
                ? { ...s, status: "active", detail: ev.detail }
                : s,
            ),
          )
          break
        case "stage_done":
          patchStages((stages) =>
            stages.map((s) => (s.id === ev.stage ? { ...s, status: "done" } : s)),
          )
          break
        case "delta":
          acc += ev.data
          patchExchange({ content: acc })
          break
        case "reset":
          // Generation restarted server-side (e.g. model rotated after a
          // quota error) — drop the partial report text.
          acc = ""
          patchExchange({ content: "" })
          break
        case "done":
          patchStages((stages) =>
            stages.map((s) => ({ ...s, status: "done" as const })),
          )
          patchExchange({ status: "done", reportStatus: "done" })
          // Persist the completed exchange server-side so the scheduler can
          // re-validate watched chats and build digests.
          {
            const target = runsRef.current.find((r) => r.id === runId)
            const ex = target?.exchanges[exIdx]
            if (target && ex) {
              void syncExchange(
                {
                  id: target.id,
                  query: target.query,
                  mode: target.exchanges[0]?.mode ?? target.mode,
                  pinned: target.pinned,
                  timestamp: target.timestamp,
                },
                exIdx,
                {
                  id: ex.id,
                  query: ex.query,
                  mode: ex.mode,
                  content: acc,
                  status: "done",
                  timestamp: ex.timestamp,
                },
              )
            }
          }
          break
        case "error":
          patchExchange({ status: "error", error: ev.message })
          break
      }
    }

    let stream: Promise<void>
    if (mode === "ask") {
      // Report Q&A: ground every follow-up on the chat's original report, not
      // on the previous answer — otherwise a long conversation drifts away
      // from the company or idea the chat is actually about.
      const chat = target ?? runsRef.current.find((r) => r.id === runId)
      const report = chat?.exchanges.find((e) => e.content.trim())?.content
      if (!report) {
        patchExchange({
          status: "error",
          error: "No report to query — run an analysis first.",
        })
        return
      }
      stream = streamAsk(report, query, onEvent, controller.signal, chat?.query)
    } else if (mode === "venture") {
      stream = streamVenture(query, onEvent, controller.signal, isDeepResearch())
    } else if (mode === "competitor" || mode === "sentiment" || mode === "metrics") {
      stream = streamAnalysis(query, mode, onEvent, controller.signal, isDeepResearch())
    } else {
      // monitor/digest exchanges arrive server-side only
      return
    }

    stream.catch((err: unknown) => {
      const message = err instanceof Error ? err.message : String(err)
      patchExchange({ status: "error", error: message })
    })
  }, [])

  const renameRun = useCallback((id: string, query: string) => {
    setRuns((rs) => rs.map((r) => (r.id === id ? { ...r, query } : r)))
  }, [])

  const deleteRun = useCallback((id: string) => {
    setRuns((rs) => rs.filter((r) => r.id !== id))
    setActiveId((cur) => (cur === id ? null : cur))
  }, [])

  const togglePin = useCallback((id: string) => {
    // Read the current value from the ref (not the updater) — React strict
    // mode double-invokes state updaters, which would flip the flag twice
    // and send the wrong value to the server.
    const current = runsRef.current.find((r) => r.id === id)?.pinned ?? false
    const newPinned = !current
    setRuns((rs) =>
      rs.map((r) => (r.id === id ? { ...r, pinned: newPinned } : r)),
    )
    // Persist immediately so the pin survives logout/login.
    void setServerChatPin(id, newPinned)
  }, [])

  const clearAll = useCallback(() => {
    setRuns([])
    setActiveId(null)
  }, [])

  return {
    runs,
    activeRun,
    activeId,
    watchedIds,
    startRun,
    setActiveId,
    renameRun,
    deleteRun,
    togglePin,
    toggleWatch,
    loadServerChats,
    clearAll,
  }
}
