import { Check } from "lucide-react"
import { cn } from "@/lib/utils"
import type { StageState } from "@/lib/use-analyze"

interface PipelineStepsProps {
  stages: StageState[]
  detail: string
  reportStatus: "pending" | "active" | "done"
}

/**
 * One pipeline row. Stacked on phones (label above its detail) and a
 * fixed-column table from `sm` up, so the detail text is never squeezed to
 * nothing on a narrow screen.
 */
const rowClass =
  "grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-x-3 gap-y-0.5 text-[13px] transition-colors sm:grid-cols-[1rem_10rem_minmax(0,1fr)] sm:items-center sm:gap-y-0"

const stateClass = (state: "pending" | "active" | "done") =>
  state === "done"
    ? "text-muted-foreground"
    : state === "active"
      ? "text-foreground"
      : "text-muted-foreground/40"

function Marker({ state }: { state: "pending" | "active" | "done" }) {
  return (
    <span
      className={cn(
        "row-span-2 pt-0.5 sm:row-span-1 sm:pt-0",
        state === "done" ? "text-emerald-500" : state === "active" ? "text-primary" : "",
      )}
    >
      {state === "done" ? <Check className="size-3.5" /> : state === "active" ? "▸" : "·"}
    </span>
  )
}

export function PipelineSteps({ stages, detail, reportStatus }: PipelineStepsProps) {
  const reportState =
    reportStatus === "done" ? "done" : reportStatus === "active" ? "active" : "pending"

  return (
    <div className="w-full max-w-md space-y-1.5 border border-border/70 bg-card/40 p-3.5 font-mono sm:p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-data-sm text-primary">VENTURE PIPELINE</span>
        <span className="cursor-blink size-1.5 bg-primary" aria-hidden />
      </div>

      {stages.map((stage) => (
        <div key={stage.id} className={cn(rowClass, "py-1.5 sm:py-1", stateClass(stage.status))}>
          <Marker state={stage.status} />
          <span className="min-w-0 sm:truncate">{stage.label}</span>
          <span className="truncate text-xs text-muted-foreground">
            {stage.status === "active" ? stage.detail || detail : ""}
          </span>
        </div>
      ))}

      <div className={cn(rowClass, "border-t border-border/60 pt-2", stateClass(reportState))}>
        <Marker state={reportState} />
        <span className="min-w-0">REPORT</span>
        <span className="truncate text-xs text-muted-foreground">
          {reportState === "active" ? detail : ""}
        </span>
      </div>
    </div>
  )
}
