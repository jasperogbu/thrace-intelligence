import { createContext, useCallback, useContext, useEffect, useState } from "react"
import type { ReactNode } from "react"
import { fetchMe, getStoredUser, logout as apiLogout, type User } from "@/lib/api"

interface AuthCtx {
  user: User | null
  ready: boolean
  setUser: (user: User | null) => void
  logout: () => void
}

const Ctx = createContext<AuthCtx>({
  user: null,
  ready: false,
  setUser: () => undefined,
  logout: () => undefined,
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => getStoredUser())
  const [ready, setReady] = useState(false)

  useEffect(() => {
    // Validate the stored token once on mount.
    fetchMe().then((validated) => {
      if (validated) {
        setUser(validated)
      } else {
        setUser(null)
        apiLogout()
      }
      setReady(true)
    })
  }, [])

  const logout = useCallback(() => {
    apiLogout()
    setUser(null)
  }, [])

  return <Ctx.Provider value={{ user, ready, setUser, logout }}>{children}</Ctx.Provider>
}

export function useAuth(): AuthCtx {
  return useContext(Ctx)
}
