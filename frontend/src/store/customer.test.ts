import { beforeEach, describe, expect, it } from "vitest";
import { useAuth } from "@/store/auth";
import { getCustomerId } from "@/store/customer";

const user = {
  id: "9f1d0c1e-3b0a-4a39-a6f4-0c5f4b5b2a10",
  email: "a@b.co",
  name: "A",
  roles: ["customer"],
};

describe("getCustomerId", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuth.getState().clear();
  });

  it("is a stable guest id while signed out", () => {
    const first = getCustomerId();
    expect(first).toMatch(/^[0-9a-f-]{36}$/);
    expect(getCustomerId()).toBe(first);
  });

  it("is the account id once signed in, so ownership checks on the server match", () => {
    const guest = getCustomerId();
    useAuth.getState().setSession({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
      expires_in: 600,
      user,
    });
    expect(getCustomerId()).toBe(user.id);
    expect(getCustomerId()).not.toBe(guest);
  });

  it("goes back to the guest id after signing out", () => {
    const guest = getCustomerId();
    useAuth.getState().setSession({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
      expires_in: 600,
      user,
    });
    useAuth.getState().clear();
    expect(getCustomerId()).toBe(guest);
  });

  it("uses the token subject while the profile is still loading after a silent refresh", () => {
    const payload = btoa(JSON.stringify({ sub: user.id })).replace(/=+$/, "");
    useAuth.getState().setTokens(`h.${payload}.s`, "r", 600);
    expect(useAuth.getState().user).toBeNull();
    expect(getCustomerId()).toBe(user.id);
  });
});
