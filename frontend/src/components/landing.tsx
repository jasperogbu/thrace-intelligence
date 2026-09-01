import { useState } from "react"
import { ArrowUp, Compass, Gauge, MessageSquareHeart, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Logo } from "@/components/logo"
import { cn } from "@/lib/utils"
import type { AnalysisType } from "@/lib/api"

const MODES: {
  id: AnalysisType
  title: string
  description: string
  icon: React.ElementType
  gradient: string
}[] = [
  {
    id: "competitor",
    title: "Competitor Analysis",
    description: "Positioning, strengths, weaknesses and strategic takeaways.",
    icon: Compass,
    gradient: "from-indigo-500/15 to-indigo-500/5",
  },
  {
    id: "sentiment",
    title: "Market Sentiment",
    description: "Positive and negative perception drivers across the web.",
    icon: MessageSquareHeart,
    gradient: "from-violet-500/15 to-violet-500/5",
  },
  {
    id: "metrics",
    title: "Performance Metrics",
    description: "Public KPIs, adoption signals and press traction.",
    icon: Gauge,
    gradient: "from-emerald-500/15 to-emerald-500/5",
  },
]

interface LandingProps {
  onAnalyze: (company: string, type: AnalysisType) => void
}

export function Landing({ onAnalyze }: LandingProps) {
  const [company, setCompany] = useState("")
  const [mode, setMode] = useState<AnalysisType>("competitor")
  const [busy, setBusy] = useState(false)

  const submit = () => {
    const value = company.trim()
    if (!value || busy) return
    setBusy(true)
    onAnalyze(value, mode)
  }

  return (
    <div className="relative flex min-h-dvh flex-col overflow-hidden">
      {/* Aurora background */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
      >
        <div className="absolute left-1/2 top-[-12rem] h-[34rem] w-[52rem] -translate-x-1/2 rounded-full bg-indigo-500/15 blur-[120px]" />
        <div className="absolute left-1/2 top-[8rem] h-[24rem] w-[38rem] -translate-x-1/2 rounded-full bg-emerald-500/10 blur-[110px]" />
        <div className="absolute inset-0 bg-grid" />
      </div>

      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 pt-6">
        <Logo />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background/60 px-3 py-1 text-xs font-medium text-muted-foreground backdrop-blur">
          <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
          Multi-agent intelligence
        </span>
      </header>

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center px-6 pb-16">
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-background/60 px-4 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur">
          <Sparkles className="size-3.5 text-violet-500" />
          Autonomous Startup Intelligence Platform
        </div>

        <h1 className="text-center text-5xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">
          Startup intelligence,
          <br />
          <span className="bg-gradient-to-r from-indigo-400 via-violet-400 to-emerald-400 bg-clip-text text-transparent">
            on autopilot.
          </span>
        </h1>

        <p className="mt-5 max-w-xl text-center text-lg leading-relaxed text-muted-foreground">
          Type any company, and a coordinated team of AI agents scours the live
          web — weighing competitive moves, market sentiment and performance
          signals into one clear, evidence-backed report.
        </p>

        {/* Input card */}
        <Card className="mt-10 w-full overflow-hidden border-border/80 bg-background/80 shadow-2xl shadow-violet-950/20 backdrop-blur-xl">
          <div className="flex items-center gap-2 px-3 py-2.5">
            <div className="flex flex-1 flex-col">
              <label htmlFor="company" className="sr-only">
                Company name
              </label>
              <input
                id="company"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="Search any company… e.g. OpenAI, Tesla"
                className="w-full bg-transparent px-2 text-[15px] text-foreground outline-none placeholder:text-muted-foreground/70"
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <Button
              size="icon"
              onClick={submit}
              disabled={!company.trim() || busy}
              className="size-9 shrink-0 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-violet-600/30 hover:from-indigo-400 hover:to-violet-500 disabled:opacity-40"
            >
              <ArrowUp className="size-4" />
            </Button>
          </div>
          <div className="flex flex-wrap gap-1.5 border-t border-border/70 px-3 py-2">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setMode(m.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  mode === m.id
                    ? "border-transparent bg-foreground text-background"
                    : "border-border bg-background text-muted-foreground hover:bg-muted",
                )}
              >
                <m.icon className="size-3.5" />
                {m.title}
              </button>
            ))}
          </div>
        </Card>

        {/* Mode cards */}
        <div className="mt-8 grid w-full gap-3 sm:grid-cols-3">
          {MODES.map((m) => (
            <Card
              key={m.id}
              className={cn(
                "group border-border/70 bg-background/50 p-4 backdrop-blur transition-all hover:-translate-y-0.5 hover:border-border hover:bg-background/80",
                m.gradient,
              )}
            >
              <div className="mb-2 inline-flex rounded-lg border border-border/70 bg-background/70 p-2">
                <m.icon className="size-4 text-foreground" />
              </div>
              <h3 className="text-sm font-medium text-foreground">{m.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {m.description}
              </p>
            </Card>
          ))}
        </div>
      </main>

      <footer className="mx-auto w-full max-w-6xl px-6 pb-6">
        <p className="text-center text-xs text-muted-foreground/70">
          JASPA · XVII MAY LTD · © 2026
        </p>
      </footer>
    </div>
  )
}
