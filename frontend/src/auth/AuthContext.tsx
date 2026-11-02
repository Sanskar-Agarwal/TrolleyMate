import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getToken, setToken } from "../api/client";
import { auth } from "../api/endpoints";
import type { User } from "../api/types";

interface AuthValue {
  user: User | null;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  register: (details: { display_name: string; email: string; password: string; household_name?: string }) => Promise<User>;
  signOut: (all?: boolean) => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    auth
      .me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    const onSignedOut = () => setUser(null);
    window.addEventListener("trolleymate:signed-out", onSignedOut);
    return () => window.removeEventListener("trolleymate:signed-out", onSignedOut);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await auth.login(email, password);
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const register = useCallback(async (details: { display_name: string; email: string; password: string; household_name?: string }) => {
    const res = await auth.register(details);
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const signOut = useCallback(async (all = false) => {
    await auth.logout(all);
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, ready, signIn, register, signOut }), [user, ready, signIn, register, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
