import { FileText, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { Run } from "@/lib/use-analyze"

const modeCode = (mode: string) =>
  mode === "venture" ? "VENT" : mode === "digest" ? "DIGE" : "COMP"
const modeLabel = (mode: string) =>
  mode === "venture"
    ? "Venture Intelligence"
    : mode === "digest"
      ? "Intelligence Digest"
      : "Company X-Ray"

interface LibraryViewProps {
  runs: Run[]
  onOpen: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}

const stripMd = (md: string) =>
  md
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\|/g, " ")
    .replace(/[#*`>_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()

export function LibraryView({ runs, onOpen, onNew, onDelete }: LibraryViewProps) {
  const completed = runs.filter((r) => r.status === "done" && r.content)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
        <p className="text-data mb-4 text-primary">// LIBRARY</p>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
            Saved reports
          </h1>
          <Button
            variant="outline"
            className="gap-2 border-border/70 font-mono text-xs tracking-wide hover:bg-card"
            onClick={onNew}
          >
            <Plus className="size-3.5" />
            new_analysis()
          </Button>
        </div>

        {completed.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="mb-4 flex size-12 items-center justify-center border border-primary/40 bg-primary/10">
              <img
                src="/thrace.png"
                alt="Thrace"
                className="size-8 rounded-sm object-cover brightness-[0.65]"
                draggable={false}
              />
            </div>
            <h2 className="font-display text-xl font-medium text-foreground">
              Library is empty
            </h2>
            <p className="mt-2 max-w-sm font-mono text-[13px] leading-relaxed text-muted-foreground">
              completed venture and x-ray reports are archived here
              automatically — run your first analysis.
            </p>
          </div>
        ) : (
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {completed.map((run) => (
              <div
                key={run.id}
                className="group relative border border-border/70 bg-card/40 p-4 text-left transition-colors hover:border-primary/40 hover:bg-card/70"
              >
                <button
                  type="button"
                  onClick={() => onOpen(run.id)}
                  className="w-full text-left"
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={cn(
                        "border px-1.5 py-0.5 font-mono text-[10px] tracking-wide",
                        run.mode === "venture"
                          ? "border-primary/40 text-primary"
                          : "border-border/70 text-muted-foreground/70",
                      )}
                    >
                      {modeCode(run.mode)}
                    </span>
                    <span className="text-data-sm text-muted-foreground/60">
                      {new Date(run.timestamp).toLocaleString([], {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  <p className="mt-2.5 truncate text-[13px] font-medium text-foreground">
                    {run.query}
                  </p>
                  <p className="mt-1 text-data-sm text-muted-foreground">
                    {modeLabel(run.mode)}
                  </p>
                  <p className="mt-2 line-clamp-2 font-mono text-xs leading-relaxed text-muted-foreground/70">
                    {stripMd(run.content).slice(0, 220)}
                  </p>
                  <p className="mt-3 flex items-center gap-1.5 font-mono text-xs text-muted-foreground/50 transition-colors group-hover:text-primary">
                    <FileText className="size-3.5" />
                    open_report()
                  </p>
                </button>
                <button
                  type="button"
                  aria-label="Delete report"
                  title="Delete report"
                  onClick={() => {
                    onDelete(run.id)
                    toast.success("Report deleted")
                  }}
                  className="absolute right-1.5 top-1.5 z-10 hidden size-7 items-center justify-center text-muted-foreground hover:bg-card hover:text-destructive group-hover:flex"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
