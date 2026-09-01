import { Compass, Gauge, MessageSquareHeart, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Logo } from "@/components/logo"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { ANALYSIS_LABELS, type AnalysisType } from "@/lib/api"

const MODES: { id: AnalysisType; icon: React.ElementType }[] = [
  { id: "competitor", icon: Compass },
  { id: "sentiment", icon: MessageSquareHeart },
  { id: "metrics", icon: Gauge },
]

export interface HistoryItem {
  id: string
  company: string
  type: AnalysisType
  timestamp: number
}

interface SidebarProps {
  mode: AnalysisType
  onModeChange: (mode: AnalysisType) => void
  history: HistoryItem[]
  onSelect: (item: HistoryItem) => void
  onNew: () => void
}

export function Sidebar({ mode, onModeChange, history, onSelect, onNew }: SidebarProps) {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border/70 bg-card/40 backdrop-blur-xl">
      <div className="flex items-center justify-between px-4 py-4">
        <Logo />
      </div>

      <div className="px-3">
        <Button
          variant="outline"
          className="w-full justify-start gap-2 border-dashed"
          onClick={onNew}
        >
          <Plus className="size-4" />
          New analysis
        </Button>
      </div>

      <div className="mt-4 px-3">
        <p className="px-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Analysis type
        </p>
        <div className="mt-2 space-y-1">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => onModeChange(m.id)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                mode === m.id
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <m.icon className="size-4" />
              {ANALYSIS_LABELS[m.id]}
            </button>
          ))}
        </div>
      </div>

      <Separator className="my-4" />

      <div className="min-h-0 flex-1 px-3">
        <p className="px-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          History
        </p>
        <ScrollArea className="mt-2 h-[calc(100%-1.5rem)]">
          {history.length === 0 ? (
            <p className="px-1 py-2 text-xs text-muted-foreground/60">
              No analyses yet. Your reports will appear here.
            </p>
          ) : (
            <div className="space-y-1">
              {history.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelect(item)}
                  className="w-full rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-muted"
                >
                  <p className="truncate text-sm text-foreground">{item.company}</p>
                  <p className="text-xs text-muted-foreground">
                    {ANALYSIS_LABELS[item.type]}
                    {" · "}
                    {new Date(item.timestamp).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </button>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>

      <div className="border-t border-border/70 px-4 py-3">
        <p className="text-[11px] leading-relaxed text-muted-foreground/70">
          JASPA · XVII MAY LTD · © 2026
        </p>
      </div>
    </aside>
  )
}
