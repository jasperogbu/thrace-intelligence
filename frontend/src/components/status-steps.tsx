import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

const PIPELINE = [
  { id: 0, label: "SEARCH", desc: "scanning the live web" },
  { id: 1, label: "REASON", desc: "agents weighing the evidence" },
  { id: 2, label: "REPORT", desc: "formatting the brief" },
]

interface StatusStepsProps {
  label: string
  detail: string
}

export function StatusSteps({ label, detail }: StatusStepsProps) {
  const activeIndex = PIPELINE.findIndex((s) =>
    label.toLowerCase().includes(s.label.toLowerCase()),
  )

  return (
    <div className="w-full max-w-md space-y-1.5 border border-border/70 bg-card/40 p-4 font-mono">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-data-sm text-primary">PROCESS</span>
        <span className="cursor-blink size-1.5 bg-primary" aria-hidden />
      </div>
      {PIPELINE.map((step, i) => {
        const active = activeIndex === i
        const done = activeIndex !== -1 ? i < activeIndex : false
        return (
          <div
            key={step.id}
            className={cn(
              "flex items-center gap-3 py-1 text-[13px] transition-colors",
              done ? "text-muted-foreground" : active ? "text-foreground" : "text-muted-foreground/40",
            )}
          >
            <span className={cn("w-6 text-right", done ? "text-emerald-500" : active ? "text-primary" : "")}>
              {done ? <Check className="ml-auto size-3.5" /> : active ? "▸" : "·"}
            </span>
            <span className="w-14">{step.label}</span>
            <span className="truncate text-xs text-muted-foreground">
              {active ? detail || step.desc : ""}
            </span>
          </div>
        )
      })}
    </div>
  )
}
