import { useEffect, useRef, useState } from "react"
import { Check, ChevronLeft, Copy, Eye, EyeOff, LoaderCircle, Menu, SquarePen } from "lucide-react"
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
  onMenu: () => void
}

export function Workspace({ run, mode, watched, onModeChange, onRun, onToggleWatch, onNew, onMenu }: WorkspaceProps) {
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

  const isVentureMode = mode === "venture"
  const hasReport = (run?.exchanges ?? []).some((e) => e.content.trim().length > 0)
  // A chat keeps the nature of its first turn. Deriving the fallback from the
  // report text alone meant a Company X-Ray whose first report came back empty
  // was re-classified as a venture — so the next message was validated as a
  // business idea instead of being asked about the company.
  const chatMode: RunMode = !run || run.mode === "venture" ? "venture" : "competitor"
  const effectiveMode: RunMode = mode === "ask" && !hasReport ? chatMode : mode

  const submit = () => {
    const value = draft.trim()
    const running = run?.status === "running"
    if (!value || running) return
    setDraft("")
    // A chat with no completed report has nothing to answer from: re-run its
    // own pipeline against the chat's original subject rather than treating
    // the new text as a fresh idea or company.
    if (run && !hasReport) {
      toast.info(`No report yet — re-running the analysis for “${run.query}”`)
      onRun(run.query, chatMode, run.id)
      return
    }
    // An open, idle chat continues in place; otherwise a new chat starts.
    onRun(value, effectiveMode, run ? run.id : undefined)
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

  // Once a chat holds a report, ASK becomes the default follow-up mode; before
  // that the chat's own pipeline is the only sensible continuation (the user
  // can still switch to VENT / COMP explicitly).
  useEffect(() => {
    if (hasReport && mode !== "ask") onModeChange("ask")
    if (!hasReport && mode === "ask") onModeChange(chatMode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasReport, run?.id, chatMode])

  const placeholder =
    mode === "ask"
      ? "ask about this report…"
      : isVentureMode
        ? "describe another idea…"
        : "query another company…"

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header */}
      <header className="flex items-center gap-1 border-b border-border/70 px-1.5 py-2 sm:gap-3 sm:px-4 sm:py-2.5">
        {/* Mobile: navigation lives in a drawer. Desktop: back to a new chat. */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onMenu}
          aria-label="Open navigation"
          className="size-9 shrink-0 md:hidden"
        >
          <Menu className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onNew}
          aria-label="Back"
          className="hidden size-8 shrink-0 md:inline-flex"
        >
          <ChevronLeft className="size-4" />
        </Button>
        <div className="flex min-w-0 flex-1 items-center gap-2 px-1 font-mono text-[13px]">
          <span className="hidden text-muted-foreground/50 sm:inline">/</span>
          <span className="min-w-0 truncate text-foreground">{run?.query ?? "—"}</span>
          <span className="hidden shrink-0 text-muted-foreground/50 sm:inline">/</span>
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
              "h-9 shrink-0 gap-1.5 px-3 font-mono text-xs sm:h-7 sm:px-2",
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
            className="h-9 shrink-0 gap-1.5 px-3 font-mono text-xs text-muted-foreground sm:h-7 sm:px-2"
            onClick={copyReport}
          >
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            <span className="hidden sm:inline">{copied ? "copied" : "copy"}</span>
          </Button>
        )}
        {/* Mobile only — on desktop the back arrow already returns to the
            new-chat screen. Without this, starting a fresh chat meant opening
            the drawer and using new_chat(). */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onNew}
          aria-label="New chat"
          title="New chat"
          className="size-9 shrink-0 text-muted-foreground md:hidden"
        >
          <SquarePen className="size-4" />
        </Button>
      </header>

      {/* Body */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6 sm:py-8">
        <div className="mx-auto w-full max-w-3xl space-y-8">
          {!run ? (
            <EmptyState />
          ) : (
            (run.exchanges ?? []).map((ex) => {
              const isFollowUp = ex.mode !== run.mode
              // Only show the stage table once stages have actually started. An
              // instant report never runs them, so it would sit at five pending.
              const showPipeline =
                ex.mode === "venture" && ex.stages.some((s) => s.status !== "pending")
              return (
                <div key={ex.id} className="space-y-4">
                  {/* Request */}
                  <div className="flex justify-end">
                    <div className="max-w-[85%] bg-primary/[0.06] px-3 py-2 font-mono text-[13px] [overflow-wrap:anywhere]">
                      <p className="break-words text-foreground">
                        <span className="text-primary">&gt;</span> {ex.query}
                      </p>
                      {isFollowUp && (
                        <p className="text-data-sm mt-1 text-muted-foreground">
                          {modeLabelFor(ex.mode)}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Response — the report is the page, so it sits directly on
                      the background with no avatar, rule or panel around it. */}
                  <div className="min-w-0">
                    {ex.status === "running" && (
                      <div className={ex.content ? "mb-4" : ""}>
                        {showPipeline ? (
                          <PipelineSteps
                            stages={ex.stages}
                            detail={ex.statusDetail}
                            reportStatus={ex.reportStatus}
                          />
                        ) : (
                          <StatusSteps label={ex.statusLabel} detail={ex.statusDetail} />
                        )}
                      </div>
                    )}

                    {ex.content && <Markdown>{ex.content}</Markdown>}

                    {ex.status === "running" && ex.content && (
                      <p className="mt-4 flex items-center gap-2 font-mono text-xs text-muted-foreground">
                        <LoaderCircle className="size-3.5 animate-spin text-primary" />
                        streaming…
                      </p>
                    )}

                    {ex.status === "error" && (
                      <div className="border border-destructive/40 bg-destructive/[0.07] px-4 py-3 font-mono text-sm text-destructive">
                        <p className="font-medium">run_failed</p>
                        <p className="mt-1 text-destructive/80 [overflow-wrap:anywhere]">
                          {ex.error}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border/70 bg-sidebar/60 px-3 py-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))] sm:px-4 sm:py-3">
        <div className="mx-auto w-full max-w-3xl">
          <div className="flex items-end gap-2 border border-border bg-card/70 px-2.5 py-2.5 focus-within:border-primary/50 focus-within:shadow-[0_0_0_1px] focus-within:shadow-primary/25 sm:gap-3 sm:px-3">
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
              className="scrollbar-hide max-h-36 min-w-0 flex-1 resize-none bg-transparent font-mono text-[13px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/60"
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
              className="size-9 shrink-0 border border-primary/40 bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground disabled:opacity-30 sm:size-7"
            >
              <ChevronLeft className="size-4 rotate-180" />
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-1 gap-2 sm:flex-none sm:gap-3">
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
                      "min-h-9 flex-1 py-2 text-data-sm transition-colors sm:min-h-0 sm:flex-none sm:px-1 sm:py-1",
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
