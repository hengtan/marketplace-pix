import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { TokenResponse, User } from "@/api/schemas";

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  expiresAt: number;
  setSession: (res: TokenResponse) => void;
  setTokens: (access: string, refresh: string | undefined, expiresIn: number) => void;
  setUser: (user: User) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      expiresAt: 0,
      setSession: (res) =>
        set({
          user: res.user,
          accessToken: res.access_token,
          refreshToken: res.refresh_token,
          expiresAt: Date.now() + res.expires_in * 1000,
        }),
      setTokens: (access, refresh, expiresIn) =>
        set({
          accessToken: access,
          refreshToken: refresh ?? get().refreshToken,
          expiresAt: Date.now() + expiresIn * 1000,
        }),
      setUser: (user) => set({ user }),
      clear: () => set({ user: null, accessToken: null, refreshToken: null, expiresAt: 0 }),
    }),
    { name: "praca-auth", version: 1 },
  ),
);

export const isSignedIn = () => Boolean(useAuth.getState().accessToken);
export const hasRole = (role: string) => useAuth.getState().user?.roles.includes(role) ?? false;
