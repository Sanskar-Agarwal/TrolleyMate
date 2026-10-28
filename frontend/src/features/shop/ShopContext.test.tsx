import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { baskets, sessions } from "../../api/endpoints";
import type { Basket, Negotiation, SessionState } from "../../api/types";
import { ShopProvider, useShop } from "./ShopContext";

const toast = vi.hoisted(() => vi.fn());
vi.mock("../../components/Toast", () => ({ useToast: () => toast }));
vi.mock("../../api/endpoints", () => ({
  baskets: { build: vi.fn(), negotiate: vi.fn(), cancelBuild: vi.fn() },
  sessions: { current: vi.fn(), get: vi.fn(), create: vi.fn(), chat: vi.fn() },
  intake: { correct: vi.fn(), clarify: vi.fn(), form: vi.fn(), confirm: vi.fn(), cancel: vi.fn() },
}));

type BuildResult = Awaited<ReturnType<typeof baskets.build>>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const previousBasket: Basket = {
  id: 42, session_id: 7, status: "accepted", goal: "balanced", total: 35, budget: 80, remaining: 45,
  items: [], summary: "Previously accepted basket", nutrition: null, requirements: null,
  metrics: null, verdict: "passed", excluded: [], notifications: [], strategy: "Balanced", cases: [],
};
const previousState: SessionState = {
  session: { id: 7, goal: "balanced", status: "basket_ready", created_at: null },
  intake: null, basket: previousBasket, meal_plan: null, chat: [],
  constraints: { version: 1, origin: "intake", payload: { budget: 80, household_size: 1, days: 7, meals_per_day: 2 } },
};
const tradeoffs: Negotiation = {
  message: "More budget or fewer days are needed.", blocked_roles: [], budget: 30, days: 7,
  person_meals: 14, shortfall: 10,
  options: [{ id: "increase_budget", label: "Increase budget", detail: "Cover every meal", budget: 40 },
    { id: "reduce_days", label: "Cover fewer days", detail: "Keep the budget", days: 4 }],
};

function wrapper({ children }: { children: ReactNode }) {
  return <ShopProvider>{children}</ShopProvider>;
}

async function showShop() {
  const hook = renderHook(() => useShop(), { wrapper });
  await waitFor(() => expect(hook.result.current.state?.basket?.id).toBe(42));
  return hook;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(sessions.current).mockResolvedValue({ ...previousState, trace: [] });
  vi.mocked(sessions.get).mockResolvedValue(previousState);
});
afterEach(cleanup);

describe("basket build cancellation", () => {
  it("waits for the build's cancelled outcome before clearing busy, retaining the previous basket", async () => {
    const pending = deferred<BuildResult>();
    vi.mocked(baskets.build).mockReturnValue(pending.promise);
    vi.mocked(baskets.cancelBuild).mockResolvedValue({ status: "cancellation_requested", trace: [] });
    const { result } = await showShop();
    let building!: Promise<void>;
    act(() => { building = result.current.build("balanced"); });
    await waitFor(() => expect(result.current.canCancelBuild).toBe(true));
    const operationId = vi.mocked(baskets.build).mock.calls[0][2];
    expect(operationId).toEqual(expect.any(String));
    expect(operationId).toBeTruthy();

    await act(async () => { await result.current.cancelBuild(); });
    expect(baskets.cancelBuild).toHaveBeenCalledExactlyOnceWith(7, operationId);
    expect(result.current.busy).toBeTruthy();
    expect(result.current.cancellingBuild).toBe(true);
    expect(result.current.state?.basket).toEqual(previousBasket);
    expect(sessions.get).not.toHaveBeenCalled();

    await act(async () => {
      pending.resolve({ status: "cancelled", message: "Build cancelled. Your previous basket is unchanged.", trace: [] });
      await building;
    });
    expect(result.current.busy).toBeNull();
    expect(result.current.cancellingBuild).toBe(false);
    expect(result.current.canCancelBuild).toBe(false);
    expect(result.current.state?.basket).toEqual(previousBasket);
    expect(result.current.state?.constraints).toEqual(previousState.constraints);
    expect(result.current.negotiation).toBeNull();
    expect(toast.mock.calls.at(-1)?.[0]).toMatch(/cancelled/i);
    expect(toast.mock.calls.some(([message]) => String(message).includes("doesn't fit"))).toBe(false);
  });

  it("keeps a committed result when cancellation arrives too late", async () => {
    const pending = deferred<BuildResult>();
    const committed = { ...previousBasket, id: 43, total: 38, status: "verified" as const };
    vi.mocked(baskets.build).mockReturnValue(pending.promise);
    vi.mocked(baskets.cancelBuild).mockResolvedValue({ status: "already_finished", outcome: "committed", trace: [] });
    vi.mocked(sessions.get).mockResolvedValue({ ...previousState, basket: committed });
    const { result } = await showShop();
    let building!: Promise<void>;
    act(() => { building = result.current.build("balanced"); });
    await waitFor(() => expect(result.current.canCancelBuild).toBe(true));
    await act(async () => { await result.current.cancelBuild(); });
    await act(async () => {
      pending.resolve({ status: "ok", basket: committed, trace: [] });
      await building;
    });
    expect(result.current.state?.basket?.id).toBe(43);
    expect(result.current.busy).toBeNull();
    expect(result.current.cancellingBuild).toBe(false);
    expect(result.current.canCancelBuild).toBe(false);
    expect(toast.mock.calls.at(-1)?.[0]).toMatch(/Basket ready/);
    expect(toast.mock.calls.some(([message]) => /^Build cancelled/i.test(String(message)))).toBe(false);
  });

  it("does not cancel anything when no build is active", async () => {
    const { result } = await showShop();
    expect(result.current.canCancelBuild).toBe(false);
    await act(async () => { await result.current.cancelBuild(); });
    expect(baskets.cancelBuild).not.toHaveBeenCalled();
    expect(result.current.state?.basket).toEqual(previousBasket);
    expect(result.current.busy).toBeNull();
  });

  it("keeps the original build active if the cancellation request fails", async () => {
    const pending = deferred<BuildResult>();
    vi.mocked(baskets.build).mockReturnValue(pending.promise);
    vi.mocked(baskets.cancelBuild).mockRejectedValue(new Error("Cancellation request could not reach the server."));
    const { result } = await showShop();
    let building!: Promise<void>;
    act(() => { building = result.current.build("balanced"); });
    await waitFor(() => expect(result.current.canCancelBuild).toBe(true));
    await act(async () => { await result.current.cancelBuild(); });
    expect(result.current.busy).toBeTruthy();
    expect(result.current.cancellingBuild).toBe(false);
    expect(result.current.error).toContain("could not reach");
    expect(result.current.state?.basket).toEqual(previousBasket);
    await act(async () => {
      pending.resolve({ status: "ok", basket: previousBasket, trace: [] });
      await building;
    });
    expect(result.current.busy).toBeNull();
  });

  it.each(["build", "negotiate"] as const)("ignores cancellation responses once %s has returned, even while refreshing", async (method) => {
    const pending = deferred<BuildResult>();
    const cancellation = deferred<Awaited<ReturnType<typeof baskets.cancelBuild>>>();
    const refreshing = deferred<SessionState>();
    vi.mocked(baskets[method]).mockReturnValueOnce(pending.promise);
    vi.mocked(baskets.cancelBuild).mockReturnValueOnce(cancellation.promise);
    vi.mocked(sessions.get).mockReturnValueOnce(refreshing.promise);
    const { result } = await showShop();
    let building!: Promise<void>;
    let cancelling!: Promise<void>;
    act(() => {
      building = method === "build" ? result.current.build("balanced")
        : result.current.negotiate({ option_id: "increase_budget", budget: 40 });
    });
    act(() => { cancelling = result.current.cancelBuild(); });
    await act(async () => { pending.resolve({ status: "ok", basket: previousBasket, trace: [] }); });
    expect(sessions.get).toHaveBeenCalledOnce();
    expect(result.current.busy).toBeTruthy();
    expect(result.current.canCancelBuild).toBe(false);
    expect(result.current.cancellingBuild).toBe(false);
    await act(async () => {
      cancellation.resolve({ status: "cancellation_requested", trace: [] });
      await cancelling;
    });
    expect(toast).not.toHaveBeenCalled();
    expect(result.current.error).toBeNull();
    await act(async () => { refreshing.resolve(previousState); await building; });
    expect(toast.mock.calls.at(-1)?.[0]).toMatch(/Basket ready/);
    expect(result.current.busy).toBeNull();
  });

  it.each(["cancellation_requested", "already_finished", "not_running", "error"] as const)(
    "ignores a late %s cancellation response from the preceding build",
    async (lateResponse) => {
      const first = deferred<BuildResult>();
      const second = deferred<BuildResult>();
      const cancellation = deferred<Awaited<ReturnType<typeof baskets.cancelBuild>>>();
      vi.mocked(baskets.build).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
      vi.mocked(baskets.cancelBuild).mockReturnValueOnce(cancellation.promise)
        .mockResolvedValueOnce({ status: "cancellation_requested", trace: [] });
      const { result } = await showShop();
      let firstBuild!: Promise<void>;
      let oldCancellation!: Promise<void>;
      act(() => { firstBuild = result.current.build("balanced"); });
      act(() => { oldCancellation = result.current.cancelBuild(); });
      await act(async () => {
        first.resolve({ status: "ok", basket: previousBasket, trace: [] });
        await firstBuild;
      });
      let secondBuild!: Promise<void>;
      act(() => { secondBuild = result.current.build("balanced"); });
      await act(async () => { await result.current.cancelBuild(); });
      const newOperationId = vi.mocked(baskets.build).mock.calls[1][2];
      expect(newOperationId).not.toBe(vi.mocked(baskets.build).mock.calls[0][2]);
      expect(baskets.cancelBuild).toHaveBeenLastCalledWith(7, newOperationId);
      expect(result.current.cancellingBuild).toBe(true);
      const toastCount = toast.mock.calls.length;
      await act(async () => {
        if (lateResponse === "error") cancellation.reject(new Error("Old cancellation failed"));
        else cancellation.resolve({ status: lateResponse, trace: [] });
        await oldCancellation;
      });
      expect(toast).toHaveBeenCalledTimes(toastCount);
      expect(result.current.error).toBeNull();
      expect(result.current.busy).toBeTruthy();
      expect(result.current.canCancelBuild).toBe(true);
      expect(result.current.cancellingBuild).toBe(true);
      await act(async () => {
        second.resolve({ status: "cancelled", message: "Build cancelled.", trace: [] });
        await secondBuild;
      });
    },
  );

  it("coalesces rapid cancellation clicks and allows retry after a failed request", async () => {
    const pending = deferred<BuildResult>();
    const cancellation = deferred<Awaited<ReturnType<typeof baskets.cancelBuild>>>();
    vi.mocked(baskets.build).mockReturnValueOnce(pending.promise);
    vi.mocked(baskets.cancelBuild).mockReturnValueOnce(cancellation.promise)
      .mockResolvedValueOnce({ status: "cancellation_requested", trace: [] });
    const { result } = await showShop();
    let building!: Promise<void>;
    act(() => { building = result.current.build("balanced"); });
    let firstClick!: Promise<void>;
    let secondClick!: Promise<void>;
    act(() => {
      firstClick = result.current.cancelBuild();
      secondClick = result.current.cancelBuild();
    });
    expect(baskets.cancelBuild).toHaveBeenCalledOnce();
    await act(async () => {
      cancellation.reject(new Error("Temporary network failure"));
      await Promise.all([firstClick, secondClick]);
    });
    expect(result.current.cancellingBuild).toBe(false);
    await act(async () => { await result.current.cancelBuild(); });
    expect(baskets.cancelBuild).toHaveBeenCalledTimes(2);
    expect(result.current.cancellingBuild).toBe(true);
    await act(async () => {
      pending.resolve({ status: "cancelled", message: "Build cancelled.", trace: [] });
      await building;
    });
  });

  it.each(["build", "negotiate"] as const)("keeps negotiation choices after a retryable %s result", async (method) => {
    vi.mocked(baskets.build).mockResolvedValueOnce({ status: "infeasible", negotiation: tradeoffs, trace: [] });
    const { result } = await showShop();
    await act(async () => { await result.current.build("balanced"); });
    expect(result.current.negotiation).toEqual(tradeoffs);
    const pending = deferred<BuildResult>();
    vi.mocked(baskets[method]).mockReturnValueOnce(pending.promise);
    let building!: Promise<void>;
    act(() => {
      building = method === "build" ? result.current.build("balanced")
        : result.current.negotiate({ option_id: "increase_budget", budget: 40 });
    });
    await waitFor(() => expect(result.current.canCancelBuild).toBe(true));
    expect(result.current.negotiation).toEqual(tradeoffs);
    const calls = vi.mocked(baskets[method]).mock.calls;
    expect(calls[calls.length - 1][2]).toEqual(expect.any(String));
    await act(async () => {
      pending.resolve({ status: "retryable", reason: "timeout", message: "The solver timed out; retry this choice.", trace: [] });
      await building;
    });
    expect(result.current.negotiation).toEqual(tradeoffs);
    expect(result.current.error).toContain("timed out");
    expect(result.current.state?.basket).toEqual(previousBasket);
    expect(result.current.busy).toBeNull();
    expect(result.current.canCancelBuild).toBe(false);
  });
});
