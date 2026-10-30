import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, getToken, setToken } from "./client";

beforeEach(() => { sessionStorage.clear(); localStorage.clear(); });
afterEach(() => vi.restoreAllMocks());

describe("authenticated API client", () => {
  it("retires legacy persistent tokens and keeps the current login in tab storage", () => {
    localStorage.setItem("trolleymate.token", "old-login");
    expect(getToken()).toBeNull();
    expect(localStorage.getItem("trolleymate.token")).toBeNull();
    setToken("current-login");
    expect(getToken()).toBe("current-login");
    expect(localStorage.getItem("trolleymate.token")).toBeNull();
  });

  it("sends the CSRF request header, JSON and explicit bearer authentication", async () => {
    setToken("current-login");
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    await api("/sessions", { body: {} });
    expect(fetcher).toHaveBeenCalledWith("/api/sessions", expect.objectContaining({
      method: "POST", headers: expect.objectContaining({
        "X-TrolleyMate-Request": "1", Authorization: "Bearer current-login", "Content-Type": "application/json",
      }),
    }));
  });

  it("clears expired or revoked tokens and informs the UI", async () => {
    setToken("revoked-login");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"detail":"Sign in to continue."}', { status: 401 }));
    const notify = vi.spyOn(window, "dispatchEvent");
    await expect(api("/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(getToken()).toBeNull();
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ type: "trolleymate:signed-out" }));
  });

  it("reports throttling without discarding the authenticated session", async () => {
    setToken("current-login");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"detail":"Try again in 30 seconds."}', { status: 429 }));
    await expect(api("/sessions", { body: {} })).rejects.toMatchObject({ status: 429, message: "Try again in 30 seconds." });
    expect(getToken()).toBe("current-login");
  });
});
