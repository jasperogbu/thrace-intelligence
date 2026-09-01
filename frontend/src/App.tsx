import { useCallback, useMemo, useState } from "react"
import { ThemeProvider } from "next-themes"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Landing } from "@/components/landing"
import { Sidebar, type HistoryItem } from "@/components/sidebar"
import { Workspace } from "@/components/workspace"
import { useAnalyze } from "@/lib/use-analyze"
import type { AnalysisType } from "@/lib/api"

function AppShell() {
  const { runs, activeRun, startRun, setActiveId } = useAnalyze()
  const [mode, setMode] = useState<AnalysisType>("competitor")
  const [view, setView] = useState<"landing" | "workspace">("landing")

  const runAnalysis = useCallback(
    (company: string, type: AnalysisType) => {
      startRun(company, type)
      setView("workspace")
    },
    [startRun],
  )

  const history: HistoryItem[] = useMemo(
    () =>
      runs
        .filter((r) => r.status !== "running")
        .map((r) => ({
          id: r.id,
          company: r.company,
          type: r.type,
          timestamp: r.timestamp,
        })),
    [runs],
  )

  const selectHistory = (item: HistoryItem) => {
    setActiveId(item.id)
    setMode(item.type)
    setView("workspace")
  }

  const newAnalysis = () => {
    setView("landing")
  }

  if (view === "landing") {
    return <Landing onAnalyze={runAnalysis} />
  }

  return (
    <div className="flex h-dvh overflow-hidden bg-background text-foreground">
      <Sidebar
        mode={mode}
        onModeChange={(m) => {
          setMode(m)
        }}
        history={history}
        onSelect={selectHistory}
        onNew={newAnalysis}
      />
      <Workspace
        run={activeRun}
        mode={mode}
        onModeChange={setMode}
        onRun={runAnalysis}
        onNew={newAnalysis}
      />
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
      <TooltipProvider delayDuration={200}>
        <AppShell />
        <Toaster position="top-center" />
      </TooltipProvider>
    </ThemeProvider>
  )
}
