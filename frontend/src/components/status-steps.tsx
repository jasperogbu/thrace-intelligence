import { Check, LoaderCircle } from "lucide-react"
import { cn } from "@/lib/utils"

const PIPELINE = [
  { id: 0, label: "Searching the web" },
  { id: 1, label: "Synthesising insights" },
  { id: 2, label: "Formatting report" },
]

interface StatusStepsProps {
  label: string
  detail: string
}

export function StatusSteps({ label, detail }: StatusStepsProps) {
  const activeIndex = PIPELINE.findIndex((s) => label.toLowerCase().includes(s.label.toLowerCase().split(" ")[0]))

  return (
    <div className="mx-auto w-full max-w-md space-y-2.5">
      {PIPELINE.map((step, i) => {
        const active = activeIndex === i || (activeIndex === -1 && i === 0)
        const done = activeIndex !== -1 ? i < activeIndex : false
        return (
          <div
            key={step.id}
            className={cn(
              "flex items-center gap-3 rounded-xl border px-4 py-3 transition-all duration-300",
              done
                ? "border-border/60 bg-background/40"
                : active
                  ? "border-violet-500/30 bg-violet-500/[0.06]"
                  : "border-border/40 bg-background/20 opacity-50",
            )}
          >
            <div
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full border transition-colors",
                done
                  ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-500"
                  : active
                    ? "border-violet-500/40 bg-violet-500/15 text-violet-500"
                    : "border-border text-muted-foreground",
              )}
            >
              {done ? (
                <Check className="size-3.5" />
              ) : active ? (
                <LoaderCircle className="size-3.5 animate-spin" />
              ) : (
                <span className="size-1.5 rounded-full bg-muted-foreground/40" />
              )}
            </div>
            <div className="flex-1">
              <p
                className={cn(
                  "text-sm font-medium",
                  done ? "text-muted-foreground" : "text-foreground",
                )}
              >
                {step.label}
              </p>
              {active && <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>}
            </div>
          </div>
        )
      })}
    </div>
  )
}
