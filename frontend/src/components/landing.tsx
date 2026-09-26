import { useEffect, useRef, useState } from "react"
import { ArrowUpRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { AnalysisType, RunMode } from "@/lib/api"

interface LandingProps {
  onAnalyze: (query: string, mode: RunMode) => void
}

const MODES = [
  { id: "venture" as const, label: "Venture Intelligence" },
  { id: "xray" as const, label: "Company X-Ray" },
]

export function Landing({ onAnalyze }: LandingProps) {
  const [idea, setIdea] = useState("")
  const [tab, setTab] = useState<"venture" | "xray">("venture")
  const [busy, setBusy] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [idea])

  const isVenture = tab === "venture"

  const submit = (value?: string, xrayType?: AnalysisType) => {
    const query = (value ?? idea).trim()
    if (!query || busy) return
    setBusy(true)
    onAnalyze(query, isVenture ? "venture" : (xrayType ?? "competitor"))
  }

  const placeholder = isVenture
    ? "e.g. Start a food processing business in Jos…"
    : "query a company... e.g. Opay"

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-terminal-grid" />
        <div className="absolute left-1/2 top-[-16rem] h-[30rem] w-[46rem] -translate-x-1/2 rounded-full bg-primary/[0.07] blur-[110px]" />
      </div>

      {/* Pinned banner */}
      <div className="z-10 flex shrink-0 items-center justify-center px-6 pt-6 pb-2 sm:pt-12">
        <p className="text-data text-center text-primary">
          // AUTONOMOUS STARTUP INTELLIGENCE
        </p>
      </div>

      {/* `my-auto` on the inner block centres the content when there is room
          and lets it scroll from the top when there is not — `justify-center`
          alone clips the top of the content on short phone viewports. */}
      <main className="relative flex min-h-0 w-full flex-1 flex-col overflow-y-auto px-4 py-6 sm:px-6 sm:py-10">
        <div className="my-auto mx-auto w-full max-w-2xl text-center">
          <h1 className="font-display text-3xl font-medium leading-[1.1] tracking-tight text-foreground sm:text-5xl sm:leading-[1.05]">
            {isVenture ? "Validate before you build." : "Research any company."}
          </h1>

          {/* Mode toggle */}
          <div className="mt-6 flex w-full border border-border/70 bg-card/40 p-1 sm:mt-8 sm:inline-flex sm:w-auto sm:max-w-full">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setTab(m.id)}
                className={cn(
                  "min-h-9 flex-1 whitespace-nowrap px-3 py-2 font-mono text-xs tracking-wide transition-colors sm:min-h-0 sm:px-4 sm:py-1.5",
                  tab === m.id
                    ? "bg-primary/[0.10] text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>

          {/* Input */}
          <div className="mt-4 w-full sm:mt-5">
            <div className="flex items-end gap-2 border border-border bg-card/60 px-3 py-3 backdrop-blur focus-within:border-primary/50 focus-within:shadow-[0_0_0_1px] focus-within:shadow-primary/30 sm:gap-3 sm:px-4 sm:py-3.5">
              <span className="pb-0.5 font-mono text-sm text-primary">&gt;</span>
              <textarea
                ref={taRef}
                value={idea}
                onChange={(e) => setIdea(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                placeholder={placeholder}
                rows={1}
                className="scrollbar-hide max-h-40 min-w-0 flex-1 resize-none bg-transparent text-left font-mono text-sm leading-6 text-foreground outline-none placeholder:text-muted-foreground/60"
                autoComplete="off"
                spellCheck={false}
                autoFocus
              />
              {idea.trim() && (
                <span className="cursor-blink mb-1 h-4 w-2 shrink-0 bg-primary" aria-hidden />
              )}
              <Button
                size="icon"
                onClick={() => submit()}
                disabled={!idea.trim() || busy}
                className="size-9 shrink-0 border border-primary/40 bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground disabled:opacity-30"
              >
                <ArrowUpRight className="size-4" />
              </Button>
            </div>
          </div>

          <p className="text-data-sm mt-6 text-muted-foreground/50 sm:mt-8">
            one analytical pass — fastest, with a few real sources attached
          </p>
        </div>
      </main>
    </div>
  )
}
