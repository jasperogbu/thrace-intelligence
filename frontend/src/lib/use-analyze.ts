import { useCallback, useRef, useState } from "react"
import { streamAnalysis, type AnalysisType } from "@/lib/api"

export interface Run {
  id: string
  company: string
  type: AnalysisType
  status: "running" | "done" | "error"
  content: string
  statusLabel: string
  statusDetail: string
  timestamp: number
  error?: string
}

export function useAnalyze() {
  const [runs, setRuns] = useState<Run[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const activeRun = runs.find((r) => r.id === activeId) ?? null

  const patchRun = (id: string, patch: Partial<Run>) => {
    setRuns((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  const startRun = useCallback((company: string, type: AnalysisType) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const id = crypto.randomUUID()
    const run: Run = {
      id,
      company,
      type,
      status: "running",
      content: "",
      statusLabel: "Searching the web",
      statusDetail: `Scanning live sources for ${company}…`,
      timestamp: Date.now(),
    }
    setRuns((rs) => [run, ...rs])
    setActiveId(id)

    let acc = ""

    streamAnalysis(
      company,
      type,
      (ev) => {
        switch (ev.type) {
          case "status":
            patchRun(id, { statusLabel: ev.label, statusDetail: ev.detail })
            break
          case "delta":
            acc += ev.data
            patchRun(id, { content: acc })
            break
          case "done":
            patchRun(id, { status: "done" })
            break
          case "error":
            patchRun(id, { status: "error", error: ev.message })
            break
        }
      },
      controller.signal,
    ).catch((err: unknown) => {
      const message = err instanceof Error ? err.message : String(err)
      patchRun(id, { status: "error", error: message })
    })
  }, [])

  return { runs, activeRun, activeId, startRun, setActiveId }
}
