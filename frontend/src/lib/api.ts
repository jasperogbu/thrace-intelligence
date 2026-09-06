export type AnalysisType = "competitor" | "sentiment" | "metrics"
export type RunMode =
  | "venture"
  | "ask"
  | "monitor"
  | "digest"
  | AnalysisType

export type VentureStageId = "validation" | "market" | "competition" | "risk" | "plan"

export type StreamEvent =
  | { type: "status"; label: string; detail: string }
  | { type: "stage_start"; stage: string; label?: string; detail?: string }
  | { type: "stage_done"; stage: string }
  | { type: "delta"; data: string }
  | { type: "reset" }
  | { type: "idea"; title: string; prompt: string; rationale: string }
  | { type: "done" }
  | { type: "error"; message: string }

export interface Health {
  status: string
  model: string | null
  agents: string[] | null
  pipelines: string[] | null
  features: string[] | null
  ready: boolean
  error: string | null
}

export const MODE_LABELS: Record<RunMode, string> = {
  venture: "Venture Intelligence",
  ask: "Report Q&A",
  monitor: "Monitoring Update",
  digest: "Intelligence Digest",
  competitor: "Competitor Analysis",
  sentiment: "Market Sentiment",
  metrics: "Performance Metrics",
}

export const MODE_CODES: Record<RunMode, string> = {
  venture: "VENT",
  ask: "ASK",
  monitor: "MONI",
  digest: "DIGE",
  competitor: "COMP",
  sentiment: "SENT",
  metrics: "METR",
}

export const VENTURE_STAGES: { id: VentureStageId; label: string }[] = [
  { id: "validation", label: "IDEA VALIDATION" },
  { id: "market", label: "MARKET & LOCATION" },
  { id: "competition", label: "COMPETITIVE LANDSCAPE" },
  { id: "risk", label: "RISK & SUCCESS" },
  { id: "plan", label: "VENTURE PLAN" },
]

export async function getHealth(): Promise<Health> {
  const res = await fetch("/api/health")
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`)
  return res.json()
}

/**
 * Read an SSE response body (via fetch streaming) and invoke `onEvent` for each
 * parsed server event.
 */
async function readSse(
  res: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
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
            event.type === "stage_done" ||
            event.type === "delta" ||
            event.type === "reset" ||
            event.type === "idea" ||
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

async function postStream(
  url: string,
  body: Record<string, unknown>,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed: ${res.status}`)
  }

  await readSse(res, onEvent)
}

/** Run the Venture Intelligence pipeline for a business idea (SSE). */
export function streamVenture(
  idea: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return postStream("/api/venture", { idea }, onEvent, signal)
}

/** Run a Company X-Ray analysis for an existing company (SSE). */
export function streamAnalysis(
  company: string,
  analysisType: AnalysisType,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return postStream(
    "/api/analyze",
    { company, analysis_type: analysisType },
    onEvent,
    signal,
  )
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
export interface User {
  id: string
  email: string
  name: string
}

const TOKEN_KEY = "thrace_token"
const USER_KEY = "thrace_user"

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function getStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as User
    return parsed && typeof parsed.id === "string" ? parsed : null
  } catch {
    return null
  }
}

function storeSession(user: User, token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    // ignore persistence failures
  }
}

function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch {
    // ignore
  }
}

function authHeaders(): Record<string, string> {
  const token = getStoredToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function apiRegister(
  email: string,
  name: string,
  password: string,
): Promise<{ user: User; token: string }> {
  const res = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ email, name, password }),
  })
  if (!res.ok) {
    const data = (await res.json().catch(() => null)) as { detail?: string } | null
    throw new Error(data?.detail ?? `Registration failed: ${res.status}`)
  }
  const data = (await res.json()) as { user: User; token: string }
  storeSession(data.user, data.token)
  return data
}

export async function apiLogin(
  email: string,
  password: string,
): Promise<{ user: User; token: string }> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const data = (await res.json().catch(() => null)) as { detail?: string } | null
    throw new Error(data?.detail ?? `Login failed: ${res.status}`)
  }
  const data = (await res.json()) as { user: User; token: string }
  storeSession(data.user, data.token)
  return data
}

export function logout(): void {
  clearSession()
}

/** Validate the stored token against the server; returns the user or null. */
export async function fetchMe(): Promise<User | null> {
  const token = getStoredToken()
  if (!token) return null
  try {
    const res = await fetch("/api/auth/me", { headers: authHeaders() })
    if (!res.ok) return null
    const data = (await res.json()) as { user: User | null }
    return data.user
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Server sync + autonomous features
// ---------------------------------------------------------------------------
export interface WatchItem {
  run_id: string
  query: string
  mode: string
  interval_hours: number
  last_run: number
}

export interface ServerExchange {
  id: string
  run_id: string
  idx: number
  kind: string
  query: string | null
  mode: string | null
  content: string | null
  status: string | null
  created_at: number
}

export interface ServerRunUpdate {
  id: string
  query: string
  mode: string
  created_at: number
  exchanges: ServerExchange[]
}

/** Push a completed exchange to the server store (fire-and-forget). */
export function syncExchange(
  run: { id: string; query: string; mode: string; pinned?: boolean; timestamp: number },
  exchangeCount: number,
  exchange: {
    id: string
    query: string
    mode: string
    content: string
    status: string
    timestamp: number
  },
): Promise<void> {
  return fetch("/api/runs/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ run: { ...run, exchangeCount }, exchange }),
  })
    .then(() => undefined)
    .catch(() => undefined)
}

/** Fetch server-originated exchanges (monitor/digest) since `since` (epoch s). */
export async function fetchUpdates(since: number): Promise<ServerRunUpdate[]> {
  try {
    const res = await fetch(`/api/updates?since=${encodeURIComponent(since)}`, {
      headers: authHeaders(),
    })
    if (!res.ok) return []
    const data = (await res.json()) as { updates?: ServerRunUpdate[] }
    return data.updates ?? []
  } catch {
    return []
  }
}

export async function getWatchlist(): Promise<WatchItem[]> {
  try {
    const res = await fetch("/api/watchlist", { headers: authHeaders() })
    if (!res.ok) return []
    const data = (await res.json()) as { watching?: WatchItem[] }
    return data.watching ?? []
  } catch {
    return []
  }
}

export function addWatch(runId: string, query: string, mode: string): Promise<void> {
  return fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ run_id: runId, query, mode }),
  })
    .then(() => undefined)
    .catch(() => undefined)
}

export function removeWatch(runId: string): Promise<void> {
  return fetch(`/api/watchlist/${encodeURIComponent(runId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  })
    .then(() => undefined)
    .catch(() => undefined)
}

/** Load the signed-in user's full chat history from the server. */
export async function fetchServerChats(): Promise<
  {
    id: string
    query: string
    mode: string
    pinned: number
    created_at: number
    exchanges: ServerExchange[]
  }[]
> {
  try {
    const res = await fetch("/api/chats", { headers: authHeaders() })
    if (!res.ok) return []
    const data = (await res.json()) as { chats?: never[] }
    return (data.chats ?? []) as never[]
  } catch {
    return []
  }
}

/** Delete a chat server-side (signed-in users only). */
export function deleteServerChat(runId: string): Promise<void> {
  return fetch(`/api/chats/${encodeURIComponent(runId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  })
    .then(() => undefined)
    .catch(() => undefined)
}

/** Pin/unpin a chat server-side so it survives logout/login. */
export function setServerChatPin(runId: string, pinned: boolean): Promise<void> {
  return fetch(`/api/chats/${encodeURIComponent(runId)}/pin`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ pinned }),
  })
    .then(() => undefined)
    .catch(() => undefined)
}

// ---------------------------------------------------------------------------
// Discover scan persistence
// ---------------------------------------------------------------------------
export interface DiscoverIdea {
  title: string
  prompt: string
  rationale: string
}

export interface DiscoverScan {
  focus: string
  log: string
  ideas: DiscoverIdea[]
  updated_at?: number
}

export async function fetchDiscoverScan(): Promise<DiscoverScan | null> {
  try {
    const res = await fetch("/api/discover/scan", { headers: authHeaders() })
    if (!res.ok) return null
    const data = (await res.json()) as { scan?: DiscoverScan | null }
    return data.scan ?? null
  } catch {
    return null
  }
}

export function saveDiscoverScan(scan: DiscoverScan): Promise<void> {
  return fetch("/api/discover/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(scan),
  })
    .then(() => undefined)
    .catch(() => undefined)
}

export function clearDiscoverScan(): Promise<void> {
  return fetch("/api/discover/scan", { method: "DELETE", headers: authHeaders() })
    .then(() => undefined)
    .catch(() => undefined)
}

/** Scan live signals for opportunity ideas (SSE). */
export function streamDiscover(
  focus: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return postStream("/api/discover", { focus }, onEvent, signal)
}

/** Ask a follow-up question about a report (SSE). */
export function streamAsk(
  content: string,
  question: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return postStream("/api/ask", { content, question }, onEvent, signal)
}
