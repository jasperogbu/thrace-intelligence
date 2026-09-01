import { useEffect, useRef, useState } from "react"
import {
  ArrowUp,
  Check,
  ChevronLeft,
  Copy,
  LoaderCircle,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Markdown } from "@/components/markdown"
import { StatusSteps } from "@/components/status-steps"
import { cn } from "@/lib/utils"
import { ANALYSIS_LABELS, type AnalysisType } from "@/lib/api"
import type { Run } from "@/lib/use-analyze"

const MODES: AnalysisType[] = ["competitor", "sentiment", "metrics"]

interface WorkspaceProps {
  run: Run | null
  mode: AnalysisType
  onModeChange: (mode: AnalysisType) => void
  onRun: (company: string, type: AnalysisType) => void
  onNew: () => void
}

export function Workspace({ run, mode, onModeChange, onRun, onNew }: WorkspaceProps) {
  const [draft, setDraft] = useState(run?.company ?? "")
  const [copied, setCopied] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setDraft((d) => d || run?.company || "")
  }, [run?.company])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [run?.content, run?.status])

  const submit = () => {
    const value = draft.trim()
    if (!value || run?.status === "running") return
    onRun(value, mode)
  }

  const copyReport = async () => {
    if (!run?.content) return
    await navigator.clipboard.writeText(run.content)
    setCopied(true)
    toast.success("Report copied to clipboard")
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 border-b border-border/70 px-4 py-3">
        <Button variant="ghost" size="icon" onClick={onNew} aria-label="Back">
          <ChevronLeft className="size-4" />
        </Button>
        <div className="flex-1">
          <p className="truncate text-sm font-medium text-foreground">
            {run?.company || "New analysis"}
          </p>
          <p className="text-xs text-muted-foreground">
            {run ? ANALYSIS_LABELS[run.type] : "Autonomous Startup Intelligence"}
          </p>
        </div>
        {run?.status === "done" && run.content && (
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" onClick={copyReport}>
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            {copied ? "Copied" : "Copy"}
          </Button>
        )}
      </header>

      {/* Body */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto w-full max-w-3xl space-y-6">
          {!run ? (
            <EmptyState />
          ) : (
            <>
              {/* User request bubble */}
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-md bg-gradient-to-br from-indigo-600 to-violet-600 px-4 py-2.5 text-sm text-white shadow-lg shadow-violet-600/20">
                  <p className="font-medium">{run.company}</p>
                  <p className="text-white/80">{ANALYSIS_LABELS[run.type]}</p>
                </div>
              </div>

              {/* JASPA response */}
              <div className="flex gap-3">
                <div className="relative flex size-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-emerald-400 text-white">
                  <Sparkles className="size-4" />
                </div>
                <div className="min-w-0 flex-1 pt-1">
                  {run.status === "running" && !run.content && (
                    <StatusSteps label={run.statusLabel} detail={run.statusDetail} />
                  )}
                  {run.status === "running" && run.content && (
                    <div className="mb-3">
                      <StatusSteps label={run.statusLabel} detail={run.statusDetail} />
                    </div>
                  )}
                  {run.content ? (
                    <div
                      className={cn(
                        "rounded-2xl rounded-tl-md border border-border/70 bg-card/50 p-5 backdrop-blur",
                        run.status === "running" && "animate-pulse-slow",
                      )}
                    >
                      <Markdown>{run.content}</Markdown>
                      {run.status === "running" && (
                        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                          <LoaderCircle className="size-3.5 animate-spin text-violet-500" />
                          Still writing…
                        </div>
                      )}
                    </div>
                  ) : null}
                  {run.status === "error" && (
                    <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
                      <p className="font-medium">Analysis failed</p>
                      <p className="mt-1 text-red-400/80">{run.error}</p>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Input bar */}
      <div className="border-t border-border/70 bg-background/60 p-4 backdrop-blur-xl">
        <div className="mx-auto w-full max-w-3xl">
          <div className="flex items-center gap-2 rounded-2xl border border-border bg-card/70 px-3 py-2 shadow-lg shadow-black/5 backdrop-blur focus-within:border-violet-500/50 focus-within:ring-1 focus-within:ring-violet-500/30">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="Analyse another company…"
              className="flex-1 bg-transparent px-1 py-1 text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
              autoComplete="off"
              spellCheck={false}
            />
            <Button
              size="icon"
              onClick={submit}
              disabled={!draft.trim() || run?.status === "running"}
              className="size-8 shrink-0 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-md shadow-violet-600/30 hover:from-indigo-400 hover:to-violet-500 disabled:opacity-40"
            >
              <ArrowUp className="size-4" />
            </Button>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <div className="flex flex-wrap gap-1.5">
              {MODES.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => onModeChange(m)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                    mode === m
                      ? "border-transparent bg-foreground text-background"
                      : "border-border text-muted-foreground hover:bg-muted",
                  )}
                >
                  {ANALYSIS_LABELS[m]}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground/60">
              Enter ↵ to run
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 via-violet-500 to-emerald-400 text-white shadow-xl shadow-violet-500/25">
        <Sparkles className="size-6" />
      </div>
      <h2 className="text-xl font-semibold text-foreground">Pick a company to begin</h2>
      <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
        Your intelligence reports will appear here, streamed live as the agents
        search the web and reason over the evidence.
      </p>
    </div>
  )
}
