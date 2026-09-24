import { useEffect } from "react"
import { ArrowUpRight, LoaderCircle, Telescope, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Markdown } from "@/components/markdown"
import {
  clearDiscover,
  hydrateDiscover,
  setDiscoverFocus,
  startDiscoverScan,
  useDiscover,
} from "@/lib/discover-store"
import { DISCOVER_MAX_IDEAS } from "@/lib/api"

interface DiscoverProps {
  onAnalyze: (query: string, mode: "venture") => void
  user: { id: string; email: string; name: string } | null
}

export function DiscoverView({ onAnalyze, user }: DiscoverProps) {
  const { focus, scanning, log, ideas, error } = useDiscover()

  // Load the account's persisted scan on first visit (or after re-login).
  useEffect(() => {
    void hydrateDiscover(user)
  }, [user])

  const hasPreviousScan = !scanning && (log.length > 0 || ideas.length > 0)
  // Defensive cap — the store already limits appends to DISCOVER_MAX_IDEAS.
  const visibleIdeas = ideas.slice(0, DISCOVER_MAX_IDEAS)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
        <p className="text-data mb-4 text-primary">// DISCOVER</p>

        <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
          Opportunities, found for you
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Agents scan live news, trends and market signals — then propose
          business ideas worth validating. One click sends any idea into the
          Venture Intelligence pipeline.
        </p>

        {/* Scan input + clear */}
        <div className="mt-6 flex max-w-xl flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex max-w-xl flex-1 items-end gap-2 border border-border bg-card/60 px-3 py-2.5 focus-within:border-primary/50 sm:gap-3">
            <span className="pb-0.5 font-mono text-sm text-primary">&gt;</span>
            <input
              value={focus}
              onChange={(e) => setDiscoverFocus(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  if (hasPreviousScan) clearDiscover()
                  startDiscoverScan()
                }
              }}
              placeholder="optional focus — e.g. fintech in Lagos, agriculture in Plateau…"
              className="min-w-0 flex-1 bg-transparent font-mono text-[13px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/60"
              autoComplete="off"
              spellCheck={false}
              disabled={scanning}
            />
            <Button
              size="sm"
              onClick={() => {
                if (hasPreviousScan) clearDiscover()
                startDiscoverScan()
              }}
              disabled={scanning}
              className="shrink-0 gap-1.5 border border-primary/40 bg-primary/10 font-mono text-xs text-primary hover:bg-primary hover:text-primary-foreground disabled:opacity-40"
            >
              {scanning ? <LoaderCircle className="size-3.5 animate-spin" /> : <Telescope className="size-3.5" />}
              {scanning ? "scanning…" : "scan_signals()"}
            </Button>
          </div>
          {hasPreviousScan && (
            <Button
              size="sm"
              variant="outline"
              onClick={clearDiscover}
              title="Clear the previous scan from your account"
              className="shrink-0 gap-1.5 border-border/70 font-mono text-xs text-muted-foreground hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="size-3.5" />
              clear_scan()
            </Button>
          )}
        </div>

        {/* Live scan log */}
        {(scanning || log) && (
          <div className="mt-6 border border-border/70 bg-card/40 px-4 py-3">
            <p className="mb-1 flex items-center gap-2 font-mono text-xs text-muted-foreground/60">
              agent scan output
              {scanning && <LoaderCircle className="size-3 animate-spin text-primary" />}
            </p>
            <div className="max-h-64 overflow-y-auto">
              {log ? (
                <Markdown className="text-xs">{log}</Markdown>
              ) : (
                <p className="font-mono text-xs text-muted-foreground/70">
                  searching live signals…
                </p>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="mt-6 border border-destructive/40 bg-destructive/[0.07] px-4 py-3 font-mono text-sm text-destructive">
            <p className="font-medium">scan_failed</p>
            <p className="mt-1 text-destructive/80">{error}</p>
          </div>
        )}

        {/* Idea cards */}
        {visibleIdeas.length > 0 && (
          <div className="mt-8">
            <p className="text-data-sm mb-3 text-muted-foreground">
              {visibleIdeas.length}{" "}
              {visibleIdeas.length === 1 ? "OPPORTUNITY" : "OPPORTUNITIES"} PROPOSED
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {visibleIdeas.map((idea) => (
                <div
                  key={idea.prompt}
                  className="group flex flex-col border border-border/70 bg-card/40 p-4 transition-colors hover:border-primary/40 hover:bg-card/70"
                >
                  <p className="text-[13px] font-medium text-foreground">{idea.title}</p>
                  <p className="mt-2 break-words border border-border/70 bg-background/60 px-2 py-1 font-mono text-[11px] leading-relaxed text-muted-foreground/80">
                    &gt; {idea.prompt}
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    {idea.rationale}
                  </p>
                  {/* Straight into the Venture Intelligence pipeline. */}
                  <div className="mt-auto pt-4">
                    <Button
                      onClick={() => onAnalyze(idea.prompt, "venture")}
                      className="w-full gap-1.5 border border-primary/40 bg-primary/10 font-mono text-xs tracking-wide text-primary hover:bg-primary hover:text-primary-foreground"
                    >
                      <ArrowUpRight className="size-3.5" />
                      validate()
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {ideas.length === 0 && !scanning && !log && (
          <div className="mt-12 flex flex-col items-center justify-center py-16 text-center">
            <div className="mb-4 flex size-12 items-center justify-center border border-primary/40 bg-primary/10">
              <Telescope className={cn("size-5 text-primary")} />
            </div>
            <h2 className="font-display text-xl font-medium text-foreground">
              No scan yet
            </h2>
            <p className="mt-2 max-w-sm font-mono text-[13px] leading-relaxed text-muted-foreground">
              run a scan — the agents will propose ideas worth validating
            </p>
          </div>
        )}

        {hasPreviousScan && (
          <p className="text-data-sm mt-8 text-muted-foreground/50">
            scan saved to your account — it stays until you clear it
          </p>
        )}
      </div>
    </div>
  )
}
