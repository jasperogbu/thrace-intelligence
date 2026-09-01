export type AnalysisType = "competitor" | "sentiment" | "metrics"

export type StreamEvent =
  | { type: "status"; label: string; detail: string }
  | { type: "stage_start"; stage: "report" }
  | { type: "delta"; data: string }
  | { type: "done" }
  | { type: "error"; message: string }

export interface Health {
  status: string
  model: string | null
  agents: string[] | null
  ready: boolean
  error: string | null
}

export const ANALYSIS_LABELS: Record<AnalysisType, string> = {
  competitor: "Competitor Analysis",
  sentiment: "Market Sentiment",
  metrics: "Performance Metrics",
}

export async function getHealth(): Promise<Health> {
  const res = await fetch("/api/health")
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`)
  return res.json()
}

/**
 * Stream an analysis from the backend over SSE (via fetch streaming).
 * Invokes `onEvent` for each parsed server event.
 */
export async function streamAnalysis(
  company: string,
  analysisType: AnalysisType,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company, analysis_type: analysisType }),
    signal,
  })

  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || `Request failed: ${res.status}`)
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error("Streaming not supported by this browser.")

  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary: number
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data:")) continue
          const payload = line.slice(5).trim()
          if (!payload) continue
          let parsed: Record<string, unknown>
          try {
            parsed = JSON.parse(payload)
          } catch {
            continue
          }
          const event = parsed as unknown as StreamEvent
          if (
            event.type === "status" ||
            event.type === "stage_start" ||
            event.type === "delta" ||
            event.type === "done" ||
            event.type === "error"
          ) {
            onEvent(event)
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
