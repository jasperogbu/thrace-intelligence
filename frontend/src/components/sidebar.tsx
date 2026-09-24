import { useState } from "react"
import {
  Compass,
  Library,
  LogOut,
  PanelLeft,
  Pin,
  PinOff,
  Plus,
  Search,
  Settings,
  Telescope,
  Trash2,
  User,
  X,
} from "lucide-react"
import { toast } from "sonner"
import { Logo } from "@/components/logo"
import { cn } from "@/lib/utils"
import type { RunMode } from "@/lib/api"

export interface HistoryItem {
  id: string
  query: string
  mode: RunMode
  timestamp: number
  content?: string
  pinned?: boolean
}

export type View = "landing" | "workspace" | "library" | "explore" | "discover" | "settings"

interface SidebarProps {
  expanded: boolean
  /** Rendered inside the mobile drawer rather than as the desktop rail. */
  isDrawer?: boolean
  onToggle: () => void
  view: View
  activeId: string | null
  history: HistoryItem[]
  user: { id: string; email: string; name: string } | null
  onNewChat: () => void
  onOpenAuth: () => void
  onLogout: () => void
  onOpenLibrary: () => void
  onOpenExplore: () => void
  onOpenDiscover: () => void
  onOpenSettings: () => void
  onSelect: (item: HistoryItem) => void
  onDelete: (id: string) => void
  onTogglePin: (id: string) => void
}
const DAY = 86_400_000

function groupOf(ts: number): "Today" | "Yesterday" | "Previous 7 days" | "Older" {
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (ts >= startToday) return "Today"
  if (ts >= startToday - DAY) return "Yesterday"
  if (ts >= startToday - 7 * DAY) return "Previous 7 days"
  return "Older"
}

const GROUP_ORDER = ["Today", "Yesterday", "Previous 7 days", "Older"] as const

export function Sidebar({
  expanded,
  isDrawer = false,
  onToggle,
  view,
  activeId,
  history,
  user,
  onNewChat,
  onOpenAuth,
  onLogout,
  onOpenLibrary,
  onOpenExplore,
  onOpenDiscover,
  onOpenSettings,
  onSelect,
  onDelete,
  onTogglePin,
}: SidebarProps) {
  const [search, setSearch] = useState("")

  const q = search.trim().toLowerCase()
  const filtered = q
    ? history.filter(
        (h) =>
          h.query.toLowerCase().includes(q) ||
          (h.content ?? "").toLowerCase().includes(q),
      )
    : history

  const groups = q
    ? [{ label: `Results (${filtered.length})`, items: filtered }]
    : [
        {
          label: "Pinned",
          items: filtered.filter((i) => i.pinned),
        },
        ...GROUP_ORDER.map((g) => ({
          label: g,
          items: filtered.filter((i) => !i.pinned && groupOf(i.timestamp) === g),
        })),
      ].filter((g) => g.items.length > 0)

  const navBtn = (active: boolean) =>
    cn(
      "flex items-center border border-transparent font-mono text-xs tracking-wide transition-colors hover:bg-card hover:text-foreground",
      expanded ? "w-full justify-start gap-2 px-2.5 py-2.5" : "w-full justify-center py-2.5",
      active ? "text-primary" : "text-muted-foreground",
    )

  return (
    <aside
      className={cn(
        "flex h-full w-full shrink-0 flex-col border-r border-border/70 bg-sidebar transition-[width] duration-200 ease-in-out md:transition-none",
        expanded ? "md:w-64" : "md:w-14",
      )}
    >
      {/* Brand + collapse toggle */}
      <div
        className={cn(
          "group/brand flex h-[57px] items-center border-b border-border/60 px-3",
          expanded ? "justify-between" : "relative justify-center px-0",
        )}
      >
        {expanded ? (
          <>
            <Logo textOnly />
            <button
              type="button"
              onClick={onToggle}
              aria-label={isDrawer ? "Close navigation" : "Collapse sidebar"}
              title={isDrawer ? "Close" : "Collapse sidebar"}
              className={cn(
                "flex items-center justify-center text-muted-foreground transition-colors hover:bg-card hover:text-foreground",
                isDrawer ? "size-9" : "size-7",
              )}
            >
              {isDrawer ? <X className="size-4" /> : <PanelLeft className="size-4" />}
            </button>
          </>
        ) : (
          <>
            <img
              src="/thrace.png"
              alt="Thrace"
              className="size-6 rounded-sm object-cover transition-opacity group-hover/brand:opacity-0 brightness-[0.65]"
              draggable={false}
            />
            <button
              type="button"
              onClick={onToggle}
              aria-label="Expand sidebar"
              title="Expand sidebar"
              className="absolute inset-0 m-auto flex size-7 items-center justify-center rounded-sm text-muted-foreground opacity-0 transition-opacity hover:bg-card hover:text-foreground group-hover/brand:opacity-100"
            >
              <PanelLeft className="size-4" />
            </button>
          </>
        )}
      </div>

      {/* Actions */}
      <div className={cn("pt-3", expanded ? "px-3" : "px-2")}>
        <button
          type="button"
          onClick={onNewChat}
          title="New chat"
          className={cn(
            "flex items-center border border-border/70 bg-card/40 font-mono text-xs tracking-wide transition-colors hover:border-primary/40 hover:bg-card",
            expanded ? "w-full justify-start gap-2 px-2.5 py-2.5" : "w-full justify-center py-2.5",
            view === "landing" && !activeId ? "text-primary" : "text-foreground",
          )}
        >
          <Plus className="size-4 shrink-0" />
          {expanded && <span>new_chat()</span>}
        </button>

        <button
          type="button"
          onClick={onOpenLibrary}
          title="Library"
          className={cn(navBtn(view === "library"), "mt-1")}
        >
          <Library className="size-4 shrink-0" />
          {expanded && <span>library()</span>}
        </button>

        <button
          type="button"
          onClick={onOpenExplore}
          title="Explore"
          className={cn(navBtn(view === "explore"), "mt-1")}
        >
          <Compass className="size-4 shrink-0" />
          {expanded && <span>explore()</span>}
        </button>

        <button
          type="button"
          onClick={onOpenDiscover}
          title="Discover — agents scan live signals and propose ideas"
          className={cn(navBtn(view === "discover"), "mt-1")}
        >
          <Telescope className="size-4 shrink-0" />
          {expanded && <span>discover()</span>}
        </button>

        <button
          type="button"
          onClick={onOpenSettings}
          title="Settings"
          className={cn(navBtn(view === "settings"), "mt-1")}
        >
          <Settings className="size-4 shrink-0" />
          {expanded && <span>settings()</span>}
        </button>
      </div>

      {/* Recent */}
      {expanded ? (
        <>
          <div className="mt-4 border-t border-border/60" />
          <div className="flex min-h-0 flex-1 flex-col px-3 pt-3">
            <div className="flex items-center gap-2 border border-border/70 bg-card/40 px-2 py-2 focus-within:border-primary/40">
              <Search className="size-3.5 shrink-0 text-muted-foreground/60" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="search history…"
                className="w-full bg-transparent font-mono text-xs text-foreground outline-none placeholder:text-muted-foreground/50"
                autoComplete="off"
                spellCheck={false}
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label="Clear search"
                  className="text-data-sm shrink-0 text-muted-foreground/60 hover:text-foreground"
                >
                  ×
                </button>
              )}
            </div>

            <div className="scrollbar-hide mt-2 min-h-0 flex-1 overflow-y-auto">
              {groups.length === 0 ? (
                <p className="px-1 py-2 font-mono text-xs text-muted-foreground/50">
                  {q ? "no_matches" : "no_chats_yet"}
                </p>
              ) : (
                <div className="space-y-3 pb-2">
                  {groups.map((group) => (
                    <div key={group.label}>
                      <p className="text-data-sm px-1 text-muted-foreground/70">
                        {group.label}
                      </p>
                      <div className="mt-1 space-y-0.5">
                        {group.items.map((item) => {
                          const active = view === "workspace" && item.id === activeId
                          return (
                            <div key={item.id} className="group relative">
                              <button
                                type="button"
                                onClick={() => onSelect(item)}
                                className={cn(
                                  "w-full border-l-2 px-2.5 py-2.5 pr-16 text-left transition-colors",
                                  active
                                    ? "border-primary bg-primary/[0.08]"
                                    : "border-transparent hover:border-primary/40 hover:bg-card",
                                )}
                              >
                                {/* No inline pin marker here: the chat already
                                    sits under the "Pinned" heading, and the
                                    action button shows the pinned state and
                                    unpins it — a second pin icon just read as
                                    a duplicate. */}
                                <p className="truncate text-[13px] text-foreground">
                                  {item.query}
                                </p>
                                <p className="text-data-sm mt-0.5 text-muted-foreground">
                                  <span className={active ? "text-primary" : ""}>
                                    {item.mode === "venture"
                                      ? "VENT"
                                      : item.mode === "digest"
                                        ? "DIGE"
                                        : "COMP"}
                                  </span>
                                  {" · "}
                                  {new Date(item.timestamp).toLocaleTimeString([], {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                  })}
                                </p>
                              </button>

                              <div className="absolute right-1 top-1/2 z-10 flex -translate-y-1/2 items-center gap-0.5 md:pointer-events-none md:opacity-0 md:transition-opacity md:group-hover:pointer-events-auto md:group-hover:opacity-100">
                                <button
                                  type="button"
                                  aria-label={item.pinned ? "Unpin" : "Pin"}
                                  title={item.pinned ? "Unpin" : "Pin"}
                                  onClick={() => onTogglePin(item.id)}
                                  className={cn(
                                    "flex size-8 items-center justify-center hover:bg-card",
                                    item.pinned
                                      ? "text-primary"
                                      : "text-muted-foreground hover:text-foreground",
                                  )}
                                >
                                  {item.pinned ? (
                                    <PinOff className="size-3.5" />
                                  ) : (
                                    <Pin className="size-3.5" />
                                  )}
                                </button>
                                <button
                                  type="button"
                                  aria-label="Delete"
                                  title="Delete"
                                  onClick={() => {
                                    onDelete(item.id)
                                    toast.success("Report deleted")
                                  }}
                                  className="flex size-8 items-center justify-center text-muted-foreground hover:bg-card hover:text-destructive"
                                >
                                  <Trash2 className="size-3.5" />
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="flex-1" />
      )}

      {/* User / account. Demarcated from the chat list by a deliberate gap
          rather than a rule — the sidebar's own divider token is barely
          visible on this background anyway. Roughly 64px of clear space. */}
      <div
        className={cn(
          "shrink-0",
          expanded ? "px-3 pb-3 pt-14" : "flex justify-center px-0 pb-3 pt-14",
        )}
      >
        {user ? (
          <div className="flex items-center gap-2.5">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-full border border-primary/40 bg-primary/10 font-mono text-[11px] uppercase text-primary">
              {(user.name || user.email).slice(0, 1)}
            </div>
            {expanded && (
              <>
                <div className="min-w-0 flex-1 leading-none">
                  <p className="truncate text-[13px] text-foreground">
                    {user.name || user.email.split("@")[0]}
                  </p>
                  <p className="text-data-sm mt-1 text-muted-foreground/70">
                    synced account
                  </p>
                </div>
                <button
                  type="button"
                  aria-label="Sign out"
                  title="Sign out"
                  onClick={onLogout}
                  className="flex size-7 items-center justify-center text-muted-foreground transition-colors hover:bg-card hover:text-destructive"
                >
                  <LogOut className="size-3.5" />
                </button>
              </>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={onOpenAuth}
            title="Sign in or create an account"
            className="flex items-center gap-2.5 transition-colors hover:text-foreground"
          >
            <div className="flex size-7 shrink-0 items-center justify-center border border-border/70 bg-card/60">
              <User className="size-3.5 text-muted-foreground" />
            </div>
            {expanded && (
              <div className="min-w-0 flex-1 text-left leading-none">
                <p className="text-[13px] text-foreground">Guest</p>
                <p className="text-data-sm mt-1 text-muted-foreground/70">
                  sign in to sync →
                </p>
              </div>
            )}
          </button>
        )}
      </div>

      {expanded && (
        <div className="hidden border-t border-border/60 px-4 py-3 md:block">
          <p className="text-data-sm text-muted-foreground/70">
            Thrace · XVII MAY LTD · © 2026
          </p>
        </div>
      )}
    </aside>
  )
}
