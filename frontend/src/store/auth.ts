import { create } from "zustand";
import type { TokenResponse, User } from "@/api/schemas";

const REFRESH_KEY = "praca-rt";
const LEGACY_KEY = "praca-auth";

function readRefresh(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function writeRefresh(token: string | null) {
  try {
    if (token) sessionStorage.setItem(REFRESH_KEY, token);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    /* storage unavailable */
  }
}

export function dropLegacySession() {
  try {
    localStorage.removeItem(LEGACY_KEY);
  } catch {
    /* storage unavailable */
  }
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  expiresAt: number;
  restoring: boolean;
  setSession: (res: TokenResponse) => void;
  setTokens: (access: string, refresh: string | undefined, expiresIn: number) => void;
  setUser: (user: User) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()((set, get) => {
  const stored = readRefresh();
  return {
    user: null,
    accessToken: null,
    refreshToken: stored,
    expiresAt: 0,
    restoring: stored !== null,
    setSession: (res) => {
      writeRefresh(res.refresh_token);
      set({
        user: res.user,
        accessToken: res.access_token,
        refreshToken: res.refresh_token,
        expiresAt: Date.now() + res.expires_in * 1000,
      });
    },
    setTokens: (access, refresh, expiresIn) => {
      const next = refresh ?? get().refreshToken;
      if (refresh) writeRefresh(refresh);
      set({
        accessToken: access,
        refreshToken: next,
        expiresAt: Date.now() + expiresIn * 1000,
      });
    },
    setUser: (user) => set({ user }),
    clear: () => {
      writeRefresh(null);
      set({ user: null, accessToken: null, refreshToken: null, expiresAt: 0 });
    },
  };
});

let pending: Promise<void> | null = null;

export function trackRestore(task: Promise<void>): Promise<void> {
  pending ??= task.finally(() => {
    pending = null;
    useAuth.setState({ restoring: false });
  });
  return pending;
}

export const whenRestored = (): Promise<void> => pending ?? Promise.resolve();
export const isSignedIn = () => Boolean(useAuth.getState().accessToken);
export const hasRole = (role: string) => useAuth.getState().user?.roles.includes(role) ?? false;
