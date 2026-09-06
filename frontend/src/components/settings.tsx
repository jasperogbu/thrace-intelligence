import { useEffect, useState } from "react"
import { useTheme } from "next-themes"
import { LoaderCircle, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { getHealth } from "@/lib/api"

interface SettingsProps {
  onClearHistory: () => void
  runCount: number
  watchedCount: number
  user: { id: string; email: string; name: string } | null
}

const THEMES = [
  { id: "dark", label: "dark" },
  { id: "light", label: "light" },
  { id: "system", label: "system" },
] as const

const AUTONOMY_LABELS: Record<string, string> = {
  persistence: "server-side persistence (SQLite)",
  watchlist_revalidation: "watchlist re-validation",
  in_app_digest: "in-app intelligence digest",
  self_critique: "agent self-critique loop",
  adaptive_research: "adaptive research budget",
  opportunity_discovery: "opportunity discovery",
  report_qa: "report Q&A",
}

export function SettingsView({ onClearHistory, runCount, watchedCount, user }: SettingsProps) {
  const { theme, setTheme } = useTheme()
  const [health, setHealth] = useState<Awaited<ReturnType<typeof getHealth>> | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [digesting, setDigesting] = useState(false)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) =>
        setHealthError(e instanceof Error ? e.message : String(e)),
      )
  }, [])

  const clear = () => {
    onClearHistory()
    setConfirming(false)
    toast.success("All history cleared")
  }

  const runDigest = async () => {
    if (digesting) return
    setDigesting(true)
    try {
      const res = await fetch("/api/digest/run", { method: "POST" })
      if (!res.ok) throw new Error(`Request failed: ${res.status}`)
      const data = (await res.json()) as {
        result?: { revalidated?: string[]; digest?: unknown }
      }
      const revalidated = data.result?.revalidated?.length ?? 0
      const digest = data.result?.digest ? 1 : 0
      if (revalidated === 0 && digest === 0) {
        toast.info("Nothing to do — no watched subjects due or updates pending")
      } else {
        toast.success(
          `Cycle complete — ${revalidated} re-validated${digest ? ", digest generated" : ""}`,
        )
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Digest trigger failed")
    } finally {
      setDigesting(false)
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
        <p className="text-data mb-4 text-primary">// SETTINGS</p>

        <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
          System
        </h1>

        {/* System status */}
        <section className="mt-8 border border-border/70 bg-card/40 p-5">
          <p className="text-data-sm text-muted-foreground">SYSTEM STATUS</p>
          {healthError ? (
            <p className="mt-3 font-mono text-sm text-destructive">
              api_unreachable — {healthError}
            </p>
          ) : health ? (
            <div className="mt-3 space-y-2 font-mono text-[13px]">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">status</span>
                <span className={health.ready ? "text-emerald-500" : "text-destructive"}>
                  {health.ready ? "● READY" : "● NOT READY"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">model</span>
                <span className="text-foreground">{health.model ?? "—"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">pipelines</span>
                <span className="text-foreground">
                  {health.pipelines?.join(" · ") ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">agents</span>
                <span className="text-foreground">{health.agents?.length ?? "—"}</span>
              </div>
              {health.error && (
                <p className="pt-1 text-xs text-destructive">{health.error}</p>
              )}
            </div>
          ) : (
            <p className="mt-3 font-mono text-sm text-muted-foreground">checking…</p>
          )}
        </section>

        {/* Agents */}
        <section className="mt-4 border border-border/70 bg-card/40 p-5">
          <p className="text-data-sm text-muted-foreground">AGENT ROSTER</p>
          <div className="mt-3 space-y-1.5">
            {(health?.agents ?? []).map((a, i) => (
              <div key={a} className="flex items-center gap-3 font-mono text-[13px]">
                <span className="text-muted-foreground/50">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="text-foreground">{a}</span>
              </div>
            ))}
            {!health && (
              <p className="font-mono text-sm text-muted-foreground">checking…</p>
            )}
          </div>
        </section>

        {/* Autonomous system */}
        <section className="mt-4 border border-border/70 bg-card/40 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-data-sm text-muted-foreground">AUTONOMOUS SYSTEM</p>
              <p className="mt-2 font-mono text-[13px] text-muted-foreground">
                {watchedCount} {watchedCount === 1 ? "subject" : "subjects"} watched —
                re-validated weekly, digested daily
              </p>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                {(health?.features ?? []).map((f) => (
                  <span key={f} className="font-mono text-xs text-muted-foreground/70">
                    <span className="text-emerald-500">●</span>{" "}
                    {AUTONOMY_LABELS[f] ?? f}
                  </span>
                ))}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 border-border/70 font-mono text-xs hover:bg-card"
              onClick={runDigest}
              disabled={digesting}
            >
              {digesting ? (
                <LoaderCircle className="size-3.5 animate-spin" />
              ) : (
                <RefreshCw className="size-3.5" />
              )}
              {digesting ? "running…" : "run_cycle_now()"}
            </Button>
          </div>
        </section>

        {/* Appearance */}
        <section className="mt-4 border border-border/70 bg-card/40 p-5">
          <p className="text-data-sm text-muted-foreground">APPEARANCE</p>
          <div className="mt-3 flex gap-2">
            {THEMES.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTheme(t.id)}
                className={cn(
                  "border px-3 py-1.5 font-mono text-xs transition-colors",
                  theme === t.id
                    ? "border-primary/50 bg-primary/[0.08] text-primary"
                    : "border-border/70 text-muted-foreground hover:border-border hover:text-foreground",
                )}
              >
                {t.label}()
              </button>
            ))}
          </div>
        </section>

        {/* Account */}
        <section className="mt-4 border border-border/70 bg-card/40 p-5">
          <p className="text-data-sm text-muted-foreground">ACCOUNT</p>
          {user ? (
            <div className="mt-3 space-y-2 font-mono text-[13px]">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">signed in as</span>
                <span className="text-foreground">{user.name || user.email}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">email</span>
                <span className="text-foreground">{user.email}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">sync</span>
                <span className="text-emerald-500">● CHATS + WATCHLIST SYNCED</span>
              </div>
            </div>
          ) : (
            <p className="mt-3 font-mono text-[13px] text-muted-foreground">
              guest session — chats stored locally in this browser. Sign in to
              sync across devices.
            </p>
          )}
        </section>

        {/* Data */}
        <section className="mt-4 border border-border/70 bg-card/40 p-5">
          <p className="text-data-sm text-muted-foreground">DATA</p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p className="font-mono text-[13px] text-muted-foreground">
              {runCount} saved {runCount === 1 ? "report" : "reports"} · stored
              locally in this browser
            </p>
            {confirming ? (
              <div className="flex gap-2">
                <Button variant="destructive" size="sm" onClick={clear}>
                  confirm_delete()
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                  cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="border-border/70 font-mono text-xs hover:bg-card"
                onClick={() => setConfirming(true)}
                disabled={runCount === 0}
              >
                clear_all_history()
              </Button>
            )}
          </div>
        </section>

        <p className="text-data-sm mt-8 text-muted-foreground/50">
          Thrace · EVOLUTION 04 · VENTURE INTELLIGENCE
        </p>
      </div>
    </div>
  )
}
