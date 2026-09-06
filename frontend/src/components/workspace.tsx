import { useEffect, useRef, useState } from "react"
import { Check, ChevronLeft, Copy, Eye, EyeOff, LoaderCircle } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Markdown } from "@/components/markdown"
import { StatusSteps } from "@/components/status-steps"
import { PipelineSteps } from "@/components/pipeline-steps"
import { cn } from "@/lib/utils"
import { MODE_LABELS, type RunMode } from "@/lib/api"
import type { Run } from "@/lib/use-analyze"

// Modes: report Q&A first (default once a chat holds a report), then the
// venture pipeline and the company X-Ray.
const MODES: { id: RunMode; code: string }[] = [
  { id: "ask", code: "ASK" },
  { id: "venture", code: "VENT" },
  { id: "competitor", code: "COMP" },
]

const modeLabelFor = (m: RunMode): string =>
  m === "venture"
    ? MODE_LABELS.venture
    : m === "ask"
      ? MODE_LABELS.ask
      : m === "monitor"
        ? MODE_LABELS.monitor
        : m === "digest"
          ? MODE_LABELS.digest
          : "Company X-Ray"

interface WorkspaceProps {
  run: Run | null
  mode: RunMode
  watched: boolean
  onModeChange: (mode: RunMode) => void
  onRun: (query: string, mode: RunMode, appendToId?: string) => void
  onToggleWatch: (id: string) => void
  onNew: () => void
}

export function Workspace({ run, mode, watched, onModeChange, onRun, onToggleWatch, onNew }: WorkspaceProps) {
  const [draft, setDraft] = useState("")
  const [copied, setCopied] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  // A fresh run (new submission or opened history item) starts with an empty
  // input so the placeholder invites the next idea instead of echoing the
  // previous query.
  useEffect(() => {
    setDraft("")
  }, [run?.id])

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${Math.min(ta.scrollHeight, 144)}px`
  }, [draft])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [run?.content, run?.status, run?.statusLabel])

  const submit = () => {
    const value = draft.trim()
    const running = run?.status === "running"
    if (!value || running) return
    setDraft("")
    // An open, idle chat continues in place; otherwise a new chat starts.
    const continueId = run && !running ? run.id : undefined
    onRun(value, effectiveMode, continueId)
  }

  const copyReport = async () => {
    if (!run?.content) return
    const parts = (run.exchanges ?? []).map((e) => e.content).filter(Boolean)
    await navigator.clipboard.writeText(
      parts.length > 1 ? parts.join("\n\n---\n\n") : run.content,
    )
    setCopied(true)
    toast.success("Report copied to clipboard")
    setTimeout(() => setCopied(false), 1600)
  }

  const isVentureMode = mode === "venture"
  const hasReport = (run?.exchanges ?? []).some((e) => e.content.trim().length > 0)
  const effectiveMode: RunMode = mode === "ask" && !hasReport ? "venture" : mode

  // Once a chat holds a report, ASK becomes the default follow-up mode (the
  // user can still switch to VENT / COMP explicitly).
  useEffect(() => {
    if (hasReport && mode !== "ask") onModeChange("ask")
    if (!hasReport && mode === "ask") onModeChange("venture")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasReport, run?.id])

  const placeholder =
    mode === "ask"
      ? "ask about this report…"
      : isVentureMode
        ? "describe another idea…"
        : "query another company…"

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header */}
      <header className="flex items-center gap-1 border-b border-border/70 px-2 py-2 sm:gap-3 sm:px-4 sm:py-2.5">
        <Button variant="ghost" size="icon" onClick={onNew} aria-label="Back" className="size-8 shrink-0 sm:size-7">
          <ChevronLeft className="size-4" />
        </Button>
        <div className="flex min-w-0 flex-1 items-center gap-2 font-mono text-[13px]">
          <span className="text-muted-foreground/50">/</span>
          <span className="truncate text-foreground">{run?.query ?? "—"}</span>
          <span className="hidden text-muted-foreground/50 sm:inline">/</span>
          <span className="hidden shrink-0 text-primary sm:inline">
            {run
              ? modeLabelFor(run.mode).toUpperCase().replace(/ /g, "_")
              : "IDLE"}
          </span>
          <span
            className={cn(
              "ml-1 inline-flex shrink-0 items-center gap-1.5 text-data-sm sm:ml-2",
              run?.status === "running" ? "text-primary" : "text-muted-foreground/60",
            )}
          >
            <span className={cn("size-1.5", run?.status === "running" ? "animate-pulse bg-primary" : "bg-muted-foreground/40")} />
            {run?.status === "running" ? "RUNNING" : run?.status === "done" ? "DONE" : "IDLE"}
          </span>
        </div>
        {run && run.status !== "running" && run.exchanges.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "shrink-0 gap-1.5 px-2 font-mono text-xs",
              watched ? "text-primary" : "text-muted-foreground",
            )}
            title={
              watched
                ? "Watching — agents re-validate this subject and report changes"
                : "Watch — keep this subject autonomously re-validated"
            }
            onClick={() => onToggleWatch(run.id)}
          >
            {watched ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
            <span className="hidden sm:inline">{watched ? "watching" : "watch"}</span>
          </Button>
        )}
        {run?.status === "done" && run.content && (
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0 gap-1.5 px-2 font-mono text-xs text-muted-foreground"
            onClick={copyReport}
          >
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            <span className="hidden sm:inline">{copied ? "copied" : "copy"}</span>
          </Button>
        )}
      </header>

      {/* Body */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-4 sm:py-6">
        <div className="mx-auto w-full max-w-3xl space-y-6">
          {!run ? (
            <EmptyState />
          ) : (
            (run.exchanges ?? []).map((ex) => (
              <div key={ex.id} className="space-y-6">
                {/* Request line */}
                <div className="flex justify-end">
                  <div className="max-w-[85%] border border-primary/40 bg-primary/[0.06] px-3 py-2 font-mono text-[13px] sm:max-w-[80%] sm:px-4">
                    <p className="break-words text-foreground">
                      <span className="text-primary">&gt;</span> {ex.query}
                    </p>
                    <p className="text-data-sm mt-0.5 text-muted-foreground">
                      {modeLabelFor(ex.mode)}
                    </p>
                  </div>
                </div>

                {/* Response */}
                <div className="flex gap-3">
                  <img
                    src="/thrace.png"
                    alt="Thrace"
                    className="mt-1 flex size-7 shrink-0 rounded-sm object-cover brightness-[0.65]"
                    draggable={false}
                  />
                  <div className="min-w-0 flex-1 pt-0.5">
                    {ex.status === "running" && ex.mode === "venture" && (
                      <div className={ex.content ? "mb-3" : ""}>
                        <PipelineSteps
                          stages={ex.stages}
                          detail={ex.statusDetail}
                          reportStatus={ex.reportStatus}
                        />
                      </div>
                    )}
                    {ex.status === "running" && ex.mode !== "venture" && (
                      <div className={ex.content ? "mb-3" : ""}>
                        <StatusSteps label={ex.statusLabel} detail={ex.statusDetail} />
                      </div>
                    )}
                    {ex.content ? (
                      <div
                        className={cn(
                          "border-l-2 border-primary/40 bg-card/50 px-5 py-5",
                          ex.status === "running" && "animate-pulse-slow",
                        )}
                      >
                        <Markdown>{ex.content}</Markdown>
                        {ex.status === "running" && (
                          <div className="mt-4 flex items-center gap-2 font-mono text-xs text-muted-foreground">
                            <LoaderCircle className="size-3.5 animate-spin text-primary" />
                            streaming…
                          </div>
                        )}
                      </div>
                    ) : null}
                    {ex.status === "error" && (
                      <div className="border-l-2 border-destructive bg-destructive/10 px-4 py-3 font-mono text-sm text-destructive">
                        <p className="font-medium">analysis_failed</p>
                        <p className="mt-1 text-destructive/80">{ex.error}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border/70 bg-sidebar/60 px-3 py-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))] sm:px-4 sm:py-3">
        <div className="mx-auto w-full max-w-3xl">
          <div className="flex items-end gap-3 border border-border bg-card/70 px-3 py-2.5 focus-within:border-primary/50 focus-within:shadow-[0_0_0_1px] focus-within:shadow-primary/25">
            <span className="pb-0.5 font-mono text-sm text-primary">&gt;</span>
            <textarea
              ref={taRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
              placeholder={placeholder}
              rows={1}
              className="scrollbar-hide max-h-36 flex-1 resize-none bg-transparent font-mono text-[13px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/60"
              autoComplete="off"
              spellCheck={false}
            />
            {draft.trim() && (
              <span className="cursor-blink mb-1 h-4 w-2 shrink-0 bg-primary" aria-hidden />
            )}
            <Button
              size="icon"
              onClick={submit}
              disabled={!draft.trim() || run?.status === "running"}
              className="size-7 shrink-0 border border-primary/40 bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground disabled:opacity-30"
            >
              <ChevronLeft className="size-4 rotate-180" />
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-4 sm:gap-3">
              {MODES.map((m) => {
                const disabled = m.id === "ask" && !hasReport
                return (
                  <button
                    key={m.id}
                    type="button"
                    disabled={disabled}
                    title={
                      m.id === "ask" && !hasReport
                        ? "available once this chat has a report"
                        : undefined
                    }
                    onClick={() => onModeChange(m.id)}
                    className={cn(
                      "px-1 py-1 text-data-sm transition-colors",
                      disabled
                        ? "cursor-not-allowed text-muted-foreground/30"
                        : mode === m.id
                          ? "text-primary"
                          : "text-muted-foreground/60 hover:text-foreground",
                    )}
                  >
                    {m.code}
                  </button>
                )
              })}
            </div>
            <p className="text-data-sm hidden text-muted-foreground/50 sm:block">RETURN ↵</p>
          </div>
        </div>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="mb-4 flex size-12 items-center justify-center border border-primary/40 bg-primary/10">
        <img
          src="/thrace.png"
          alt="Thrace"
          className="size-8 rounded-sm object-cover brightness-[0.65]"
          draggable={false}
        />
      </div>
      <h2 className="font-display text-2xl font-medium text-foreground">
        Run an analysis
      </h2>
      <p className="mt-2 max-w-sm font-mono text-[13px] leading-relaxed text-muted-foreground">
        describe a business idea or query a company — the agents will search,
        crawl and reason, streaming the intelligence into this terminal.
      </p>
    </div>
  )
}
