import { useEffect, useRef, useState } from "react"
import { ArrowLeft, Eye, EyeOff, LoaderCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { apiLogin, apiRegister, type User } from "@/lib/api"

interface AuthViewProps {
  onAuthed: (user: User) => void
  onBack?: () => void
}

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path
        fill="#4285F4"
        d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09C3.26 21.3 7.31 24 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.62l3.98 3.09c.95-2.85 3.6-4.96 6.73-4.96z"
      />
    </svg>
  )
}

export function AuthView({ onAuthed, onBack }: AuthViewProps) {
  const [tab, setTab] = useState<"login" | "register">("login")
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const popupRef = useRef<Window | null>(null)

  const isLogin = tab === "login"

  // Receive the OAuth result from the popup window.
  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== window.location.origin) return
      const data = ev.data as
        | { type: string; user?: User; token?: string }
        | null
      if (!data || data.type !== "thrace_google_auth") return
      if (data.user && data.token) {
        try {
          localStorage.setItem("thrace_token", data.token)
          localStorage.setItem("thrace_user", JSON.stringify(data.user))
        } catch {
          // ignore
        }
        onAuthed(data.user)
      }
      popupRef.current?.close()
      popupRef.current = null
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [onAuthed])

  // Surface OAuth errors from the URL (popup fallback redirect).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const googleError = params.get("google_error")
    if (googleError) {
      setError(
        googleError === "denied"
          ? "Google sign-in was cancelled."
          : googleError === "state"
            ? "Google sign-in expired — please try again."
            : `Google sign-in failed: ${googleError}`,
      )
      window.history.replaceState({}, "", "/auth")
    }
  }, [])

  const signInWithGoogle = async () => {
    if (busy) return
    setError(null)
    try {
      const res = await fetch("/api/auth/google/url")
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as { detail?: string } | null
        throw new Error(data?.detail ?? "Google sign-in is unavailable.")
      }
      const data = (await res.json()) as { url: string }
      popupRef.current = window.open(
        data.url,
        "thrace_google",
        "width=520,height=680,resizable,scrollbars",
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start Google sign-in.")
    }
  }

  const submit = async () => {
    if (busy) return
    if (!email.trim() || !password) {
      setError("Email and password are required.")
      return
    }
    setBusy(true)
    setError(null)
    try {
      const data = isLogin
        ? await apiLogin(email.trim(), password)
        : await apiRegister(email.trim(), name.trim(), password)
      onAuthed(data.user)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Authentication failed.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-terminal-grid" />
        <div className="absolute left-1/2 top-[-16rem] h-[30rem] w-[46rem] -translate-x-1/2 rounded-full bg-primary/[0.07] blur-[110px]" />
      </div>

      <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-5 py-10 sm:px-6">
        {/* Brand */}
        <div className="mb-8 flex flex-col items-center text-center">
          <img
            src="/thrace.png"
            alt="Thrace"
            className="mb-4 size-12 rounded-sm object-cover brightness-[0.65]"
            draggable={false}
          />
          <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
            Thrace
          </h1>
          <p className="mt-2 font-mono text-[13px] leading-relaxed text-muted-foreground">
            autonomous startup intelligence — validate before you build
          </p>
        </div>

        {/* Google sign-in */}
        <Button
          onClick={() => void signInWithGoogle()}
          disabled={busy}
          className="h-12 w-full gap-3 border border-border bg-card font-mono text-sm text-foreground hover:bg-card/70 disabled:opacity-40 sm:h-11 sm:text-[13px]"
        >
          <GoogleIcon className="size-4 shrink-0" />
          <span className="truncate">{isLogin ? "sign in with google" : "sign up with google"}</span>
        </Button>

        <div className="my-6 flex items-center gap-3">
          <span className="h-px flex-1 bg-border/70" />
          <span className="font-mono text-xs text-muted-foreground/60">or</span>
          <span className="h-px flex-1 bg-border/70" />
        </div>

        {/* Tab toggle */}
        <div className="mb-5 inline-flex border border-border/70 bg-card/40 p-1">
          {(["login", "register"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => {
                setTab(t)
                setError(null)
              }}
              className={`flex-1 px-4 py-1.5 font-mono text-xs tracking-wide transition-colors ${
                tab === t
                  ? "bg-primary/[0.10] text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t === "login" ? "sign_in()" : "register()"}
            </button>
          ))}
        </div>

        {/* Email form */}
        <div className="space-y-3">
          {!isLogin && (
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="name"
              autoComplete="name"
              className="w-full border border-border bg-card/60 px-3 py-2.5 font-mono text-[13px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/50"
            />
          )}
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                void submit()
              }
            }}
            placeholder="email"
            autoComplete="email"
            className="w-full border border-border bg-card/60 px-3 py-2.5 font-mono text-[13px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/50"
          />
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  void submit()
                }
              }}
              placeholder={isLogin ? "password" : "password (min 8 characters)"}
              autoComplete={isLogin ? "current-password" : "new-password"}
              className="w-full border border-border bg-card/60 px-3 py-2.5 pr-10 font-mono text-[13px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/50"
            />
            <button
              type="button"
              aria-label={showPassword ? "Hide password" : "Show password"}
              title={showPassword ? "Hide password" : "Show password"}
              onClick={() => setShowPassword((s) => !s)}
              className="absolute right-2 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
            >
              {showPassword ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
            </button>
          </div>
        </div>

        {error && (
          <p className="mt-3 border border-destructive/40 bg-destructive/[0.07] px-3 py-2 font-mono text-xs text-destructive">
            {error}
          </p>
        )}

        <Button
          onClick={() => void submit()}
          disabled={busy}
          className="mt-6 h-12 gap-2 border border-primary/40 bg-primary/10 font-mono text-sm tracking-wide text-primary hover:bg-primary hover:text-primary-foreground disabled:opacity-40 sm:h-11 sm:text-[13px]"
        >
          {busy && <LoaderCircle className="size-3.5 animate-spin" />}
          <span className="truncate">{isLogin ? "sign_in()" : "create_account()"}</span>
        </Button>

        <p className="text-data-sm mt-8 text-center text-muted-foreground/50">
          an account is required to use Thrace — your data stays yours
        </p>

        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="mt-4 inline-flex items-center gap-1.5 self-center font-mono text-xs text-muted-foreground/60 transition-colors hover:text-foreground"
          >
            <ArrowLeft className="size-3" />
            back
          </button>
        )}
      </main>
    </div>
  )
}
