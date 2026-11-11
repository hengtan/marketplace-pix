import { refreshOnce, request } from "@/api/client";
import { api } from "@/api/endpoints";
import { userSchema } from "@/api/schemas";
import { dropLegacySession, trackRestore, useAuth } from "@/store/auth";

async function restore(): Promise<void> {
  if (!(await refreshOnce())) return;
  try {
    const user = await request("/api/auth/me", { schema: userSchema, waitForRestore: false });
    useAuth.getState().setUser(user);
  } catch {
    useAuth.getState().clear();
  }
}

export function restoreSession(): Promise<void> {
  dropLegacySession();
  if (!useAuth.getState().refreshToken) return Promise.resolve();
  return trackRestore(restore());
}

export async function signOut(): Promise<void> {
  const { refreshToken, clear } = useAuth.getState();
  clear();
  if (!refreshToken) return;
  try {
    await api.logout(refreshToken);
  } catch {
    /* the local session is already gone */
  }
}
