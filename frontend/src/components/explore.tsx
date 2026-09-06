import { ArrowUpRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { type AnalysisType, type RunMode } from "@/lib/api"

interface ExploreProps {
  onAnalyze: (query: string, mode: RunMode) => void
}

const VENTURE_EXAMPLES: { title: string; prompt: string; desc: string }[] = [
  {
    title: "Food processing in Jos",
    prompt: "Start a food processing business in Jos, Nigeria",
    desc: "Agro-value chain, local produce sourcing and urban demand.",
  },
  {
    title: "Logistics & delivery in Abuja",
    prompt: "Start a logistics and last-mile delivery service in Abuja, Nigeria",
    desc: "E-commerce fulfilment gaps and intra-city courier economics.",
  },
  {
    title: "Poultry farming in Plateau State",
    prompt: "Start a poultry farming business in Plateau State, Nigeria",
    desc: "Feed costs, biosecurity, and offtake to retail markets.",
  },
  {
    title: "On-demand laundry in Lagos",
    prompt: "Open an on-demand laundry service in Lagos, Nigeria",
    desc: "Density, disposable income and operational logistics.",
  },
  {
    title: "Solar installation in Kano",
    prompt: "Start a solar panel installation business in Kano, Nigeria",
    desc: "Energy deficit, financing models and distribution channels.",
  },
  {
    title: "EdTech tutoring platform",
    prompt: "Launch an online tutoring platform for Nigerian secondary school students",
    desc: "Exam prep demand, payment rails and mobile-first delivery.",
  },
]

const XRAY_EXAMPLES: { company: string; type: AnalysisType; desc: string }[] = [
  {
    company: "Opay",
    type: "competitor",
    desc: "Positioning, strengths and weaknesses of the payments giant.",
  },
  {
    company: "Moniepoint",
    type: "metrics",
    desc: "Adoption signals, KPIs and traction of the POS disruptor.",
  },
  {
    company: "Flutterwave",
    type: "sentiment",
    desc: "What users, forums and reviews say about the fintech.",
  },
]

export function ExploreView({ onAnalyze }: ExploreProps) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
        <p className="text-data mb-4 text-primary">// EXPLORE</p>

        <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
          Start from an example
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
          One-click prompts that launch the agents immediately — a quick tour of
          what Thrace can investigate.
        </p>

        {/* Venture examples */}
        <div className="mt-8">
          <div className="flex items-center justify-between">
            <p className="text-data-sm text-muted-foreground">
              01 · VENTURE INTELLIGENCE
            </p>
            <p className="text-data-sm text-muted-foreground/60">
              validate → plan
            </p>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {VENTURE_EXAMPLES.map((ex) => (
              <button
                key={ex.prompt}
                type="button"
                onClick={() => onAnalyze(ex.prompt, "venture")}
                className="group border border-border/70 bg-card/40 p-4 text-left transition-colors hover:border-primary/40 hover:bg-card/70"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[13px] font-medium text-foreground">{ex.title}</p>
                  <ArrowUpRight className="size-4 shrink-0 text-muted-foreground/40 transition-colors group-hover:text-primary" />
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  {ex.desc}
                </p>
                <p className="mt-3 truncate border border-border/70 bg-background/60 px-2 py-1 font-mono text-[11px] text-muted-foreground/70">
                  &gt; {ex.prompt}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* X-Ray examples */}
        <div className="mt-10">
          <div className="flex items-center justify-between">
            <p className="text-data-sm text-muted-foreground">02 · COMPANY X-RAY</p>
            <p className="text-data-sm text-muted-foreground/60">research a business</p>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {XRAY_EXAMPLES.map((ex) => (
              <button
                key={ex.company + ex.type}
                type="button"
                onClick={() => onAnalyze(ex.company, ex.type)}
                className="group border border-border/70 bg-card/40 p-4 text-left transition-colors hover:border-primary/40 hover:bg-card/70"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[13px] font-medium text-foreground">{ex.company}</p>
                  <span
                    className={cn(
                      "border px-1.5 py-0.5 font-mono text-[10px] tracking-wide uppercase",
                      "border-border/70 text-muted-foreground/70",
                    )}
                  >
                    {ex.type}
                  </span>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  {ex.desc}
                </p>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
