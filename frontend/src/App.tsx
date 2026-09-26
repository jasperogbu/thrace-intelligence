import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, Menu } from "lucide-react";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AuthView } from "@/components/auth";
import { Landing } from "@/components/landing";
import { LibraryView } from "@/components/library";
import { ExploreView } from "@/components/explore";
import { DiscoverView } from "@/components/discover";
import { SettingsView } from "@/components/settings";
import { Sidebar, type HistoryItem, type View } from "@/components/sidebar";
import { Workspace } from "@/components/workspace";
import { AuthProvider, useAuth } from "@/lib/auth";
import { useAnalyze } from "@/lib/use-analyze";
import { fetchServerChats, deleteServerChat } from "@/lib/api";
import { resetDiscoverHydration } from "@/lib/discover-store";
import type { RunMode } from "@/lib/api";
import { toast } from "sonner";

const SIDEBAR_KEY = "thrace_sidebar";
/** Pre-rename key — read once as a fallback so the preference survives. */
const LEGACY_SIDEBAR_KEY = "jaspa_sidebar";

function AppShell() {
  const { user, ready, setUser, logout } = useAuth();
  const {
    runs,
    activeRun,
    activeId,
    watchedIds,
    startRun,
    setActiveId,
    deleteRun,
    togglePin,
    toggleWatch,
    clearAll,
    loadServerChats,
  } = useAnalyze();
  const [mode, setMode] = useState<RunMode>("venture");
  const [view, setView] = useState<View>(() =>
    activeRun ? "workspace" : "landing",
  );
  const [sidebarExpanded, setSidebarExpanded] = useState<boolean>(() => {
    try {
      const stored =
        localStorage.getItem(SIDEBAR_KEY) ??
        localStorage.getItem(LEGACY_SIDEBAR_KEY);
      return stored !== "collapsed";
    } catch {
      return true;
    }
  });
  // Mobile drawer (overlay sidebar); independent of the desktop collapse.
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleSidebar = useCallback(() => {
    setSidebarExpanded((e) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, e ? "collapsed" : "expanded");
      } catch {
        // ignore persistence failures
      }
      return !e;
    });
  }, []);

  // Any navigation closes the drawer.
  const navigate = useCallback((v: View) => {
    setView(v);
    setDrawerOpen(false);
  }, []);

  const newChat = useCallback(() => {
    setActiveId(null);
    setView("landing");
    setDrawerOpen(false);
  }, [setActiveId]);

  const runAnalysis = useCallback(
    (query: string, runMode: RunMode, appendToId?: string) => {
      // A new chat adopts the nature it was started with; an existing chat
      // keeps its own (openRun/selectHistory set it when it was opened).
      if (!appendToId)
        setMode(runMode === "venture" ? "venture" : "competitor");
      startRun(query, runMode, appendToId);
      setView("workspace");
    },
    [startRun],
  );

  // Entering a signed-in state always lands on a fresh chat. This covers the
  // explicit sign-in (handleAuthed below) and the page-load case where a
  // stored session is restored — without it, `activeId` is rehydrated from
  // localStorage and a refresh drops the user back into their last
  // conversation instead of a new chat. History is untouched, so the sidebar
  // still lists everything; only the selection is cleared.
  //
  // The ref guards against re-firing: this must happen once per page load, not
  // on every re-render or every `user` identity change.
  const landedOnFreshChat = useRef(false);
  useEffect(() => {
    if (!ready || !user || landedOnFreshChat.current) return;
    landedOnFreshChat.current = true;
    setActiveId(null);
    setView("landing");
  }, [ready, user, setActiveId]);

  // Load the signed-in user's chat history from the server (once per login).
  useEffect(() => {
    if (ready && user) {
      fetchServerChats().then((chats) => {
        if (chats.length > 0) loadServerChats(chats);
      });
    }
  }, [ready, user, loadServerChats]);

  const handleAuthed = useCallback(
    (authedUser: NonNullable<typeof user>) => {
      setUser(authedUser);
      toast.success(`Signed in as ${authedUser.email}`);
      // Signing in always lands on a fresh chat. Without this, `activeId`
      // keeps whatever was selected before — an anonymous chat from a guest
      // session, or the last chat of whichever account was signed out of — so
      // the user drops straight back into a conversation they did not open
      // after authenticating.
      newChat();
    },
    [setUser, newChat],
  );

  const handleLogout = useCallback(() => {
    logout();
    clearAll();
    resetDiscoverHydration();
    toast.success("Signed out");
    setView("landing");
  }, [logout, clearAll]);

  const history: HistoryItem[] = useMemo(
    () =>
      runs
        .filter((r) => r.status !== "running")
        .map((r) => ({
          id: r.id,
          query: r.query,
          mode: r.mode,
          timestamp: r.timestamp,
          content: r.content,
          pinned: r.pinned,
        })),
    [runs],
  );

  const selectHistory = useCallback(
    (item: HistoryItem) => {
      setActiveId(item.id);
      // Two UI modes only; legacy sentiment/metrics runs open as X-Ray.
      setMode(item.mode === "venture" ? "venture" : "competitor");
      setView("workspace");
      setDrawerOpen(false);
    },
    [setActiveId],
  );

  const openRun = useCallback(
    (id: string) => {
      const run = runs.find((r) => r.id === id);
      // Chats keep their nature (venture/x-ray); ask/monitor/digest turns
      // display per exchange inside the workspace.
      if (run) setMode(run.mode === "venture" ? "venture" : "competitor");
      setActiveId(id);
      setView("workspace");
      setDrawerOpen(false);
    },
    [runs, setActiveId],
  );

  const handleDelete = useCallback(
    (id: string) => {
      deleteRun(id);
      void deleteServerChat(id);
      if (id === activeId) setView("landing");
    },
    [deleteRun, activeId],
  );

  const handleClearHistory = useCallback(() => {
    clearAll();
    setView("settings");
  }, [clearAll]);

  // Lock body scroll while the mobile drawer is open.
  useEffect(() => {
    document.body.style.overflow = drawerOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [drawerOpen]);

  const renderSidebar = (mobile: boolean) => (
    <Sidebar
      expanded={mobile ? true : sidebarExpanded}
      isDrawer={mobile}
      onToggle={mobile ? () => setDrawerOpen(false) : toggleSidebar}
      view={view}
      activeId={activeId}
      history={history}
      user={user}
      onNewChat={newChat}
      onOpenAuth={handleLogout}
      onLogout={handleLogout}
      onOpenLibrary={() => navigate("library")}
      onOpenExplore={() => navigate("explore")}
      onOpenDiscover={() => navigate("discover")}
      onOpenSettings={() => navigate("settings")}
      onSelect={selectHistory}
      onDelete={handleDelete}
      onTogglePin={togglePin}
    />
  );

  return (
    <div className="app-h flex h-dvh overflow-hidden bg-background text-foreground">
      {/* Hard gate: no feature is reachable until the user signs in. */}
      {!ready ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <LoaderCircle className="size-5 animate-spin text-primary" />
        </div>
      ) : !user ? (
        <AuthView onAuthed={handleAuthed} />
      ) : (
        <>
          {/* Desktop / tablet sidebar */}
          <div className="hidden md:flex">{renderSidebar(false)}</div>

          {/* Mobile drawer */}
          <div
            className={cn(
              "fixed inset-0 z-50 md:hidden",
              drawerOpen ? "pointer-events-auto" : "pointer-events-none",
            )}
            aria-hidden={!drawerOpen}
          >
            <div
              className={cn(
                "absolute inset-0 bg-black/60 transition-opacity duration-200",
                drawerOpen ? "opacity-100" : "opacity-0",
              )}
              onClick={() => setDrawerOpen(false)}
            />
            <div
              className={cn(
                "absolute inset-y-0 left-0 w-72 max-w-[85vw] shadow-2xl transition-transform duration-200 ease-out",
                drawerOpen ? "translate-x-0" : "-translate-x-full",
              )}
              role="dialog"
              aria-label="Navigation"
            >
              {renderSidebar(true)}
            </div>
          </div>

          <div className="flex min-w-0 flex-1 flex-col">
            {/* Mobile top bar — the chat screen renders its own header, so this
                would otherwise stack a second bar above it. */}
            {view !== "workspace" && (
              <div className="flex items-center gap-2 border-b border-border/70 bg-sidebar/60 px-2 py-2 md:hidden">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setDrawerOpen(true)}
                  aria-label="Open navigation"
                  className="size-9"
                >
                  <Menu className="size-5" />
                </Button>
                <img
                  src="/thrace.png"
                  alt="Thrace"
                  className="size-6 rounded-sm object-cover brightness-[0.65]"
                  draggable={false}
                />
                <span className="font-display text-base font-medium tracking-tight text-foreground">
                  Thrace
                </span>
                {view !== "landing" && (
                  <span className="ml-auto font-mono text-[11px] uppercase tracking-widest text-primary">
                    {view}
                  </span>
                )}
              </div>
            )}

            {view === "landing" && <Landing onAnalyze={runAnalysis} />}
            {view === "library" && (
              <LibraryView
                runs={runs}
                onOpen={openRun}
                onNew={newChat}
                onDelete={handleDelete}
              />
            )}
            {view === "explore" && <ExploreView onAnalyze={runAnalysis} />}
            {view === "discover" && (
              <DiscoverView onAnalyze={runAnalysis} user={user} />
            )}
            {view === "settings" && (
              <SettingsView
                onClearHistory={handleClearHistory}
                runCount={runs.filter((r) => r.status === "done").length}
                watchedCount={watchedIds.size}
                user={user}
              />
            )}
            {view === "workspace" && (
              <Workspace
                run={activeRun}
                mode={mode}
                watched={activeRun ? watchedIds.has(activeRun.id) : false}
                onModeChange={setMode}
                onRun={runAnalysis}
                onToggleWatch={toggleWatch}
                onNew={newChat}
                onMenu={() => setDrawerOpen(true)}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem
      disableTransitionOnChange
    >
      <TooltipProvider delayDuration={200}>
        <AuthProvider>
          <AppShell />
          <Toaster position="top-center" />
        </AuthProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}
