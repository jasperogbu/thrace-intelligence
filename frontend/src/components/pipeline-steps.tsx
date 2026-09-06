import { Check } from "lucide-react"
import { cn } from "@/lib/utils"
import type { StageState } from "@/lib/use-analyze"

interface PipelineStepsProps {
  stages: StageState[]
  detail: string
  reportStatus: "pending" | "active" | "done"
}

export function PipelineSteps({ stages, detail, reportStatus }: PipelineStepsProps) {
  return (
    <div className="w-full max-w-md space-y-1.5 border border-border/70 bg-card/40 p-4 font-mono">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-data-sm text-primary">VENTURE PIPELINE</span>
        <span className="cursor-blink size-1.5 bg-primary" aria-hidden />
      </div>
      {stages.map((stage) => {
        const active = stage.status === "active"
        const done = stage.status === "done"
        return (
          <div
            key={stage.id}
            className={cn(
              "flex items-center gap-3 py-1 text-[13px] transition-colors",
              done
                ? "text-muted-foreground"
                : active
                  ? "text-foreground"
                  : "text-muted-foreground/40",
            )}
          >
            <span
              className={cn(
                "w-6 text-right",
                done ? "text-emerald-500" : active ? "text-primary" : "",
              )}
            >
              {done ? <Check className="ml-auto size-3.5" /> : active ? "▸" : "·"}
            </span>
            <span className="w-44 shrink-0">{stage.label}</span>
            <span className="truncate text-xs text-muted-foreground">
              {active ? stage.detail || detail : ""}
            </span>
          </div>
        )
      })}
      <div
        className={cn(
          "flex items-center gap-3 border-t border-border/60 pt-2 text-[13px]",
          reportStatus === "done"
            ? "text-muted-foreground"
            : reportStatus === "active"
              ? "text-foreground"
              : "text-muted-foreground/40",
        )}
      >
        <span
          className={cn(
            "w-6 text-right",
            reportStatus === "done"
              ? "text-emerald-500"
              : reportStatus === "active"
                ? "text-primary"
                : "",
          )}
        >
          {reportStatus === "done" ? (
            <Check className="ml-auto size-3.5" />
          ) : reportStatus === "active" ? (
            "▸"
          ) : (
            "·"
          )}
        </span>
        <span className="w-44 shrink-0">REPORT</span>
        <span className="truncate text-xs text-muted-foreground">
          {reportStatus === "active" ? detail : ""}
        </span>
      </div>
    </div>
  )
}
