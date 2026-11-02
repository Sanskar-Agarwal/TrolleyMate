import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { baskets } from "../../api/endpoints";
import type { Basket } from "../../api/types";
import { useShop } from "../shop/ShopContext";
import BasketView from "./BasketView";

vi.mock("../shop/ShopContext", () => ({ useShop: vi.fn() }));
vi.mock("../../api/endpoints", () => ({ baskets: { accept: vi.fn() } }));
const newSession = vi.fn();
const setView = vi.fn();
const base = { id: 42, status: "verified", goal: "balanced", items: [], total: 60, budget: 70,
  remaining: 10, nutrition: null, notifications: [], excluded: [] } as unknown as Basket;

function show(status: Basket["status"] = "verified", error: string | null = null) {
  function Harness() {
    const [basket, setBasket] = useState({ ...base, status });
    vi.mocked(useShop).mockReturnValue({ state: { basket }, busy: null, error, setBasket, setView, newSession,
      run: async (_label: string, action: () => Promise<unknown>) => {
        try { return await action(); } catch { return undefined; }
      },
    } as unknown as ReturnType<typeof useShop>);
    return <BasketView />;
  }
  return render(<Harness />);
}

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom lacks native dialog methods; browser UAT checks native behaviour.
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.mocked(baskets.accept).mockResolvedValue({ basket: { ...base, status: "accepted" }, trace: [] });
});
afterEach(cleanup);

describe("accepted basket next steps", () => {
  it("opens after acceptance and routes to meal planning with the basket retained", async () => {
    show();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Accept basket" }));
    expect(await screen.findByRole("dialog", { name: "Your basket is ready" })).toBeTruthy();
    expect(baskets.accept).toHaveBeenCalledExactlyOnceWith(42);
    expect(screen.getByText(/no order is sent to a retailer/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make meal plan" }));
    expect(setView).toHaveBeenCalledExactlyOnceWith("meals");
    expect(newSession).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not show success choices when acceptance fails", async () => {
    vi.mocked(baskets.accept).mockRejectedValue(new Error("Could not save"));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Accept basket" }));
    await waitFor(() => expect(baskets.accept).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Next steps" })).toBeNull();
  });

  it("lets an accepted basket reopen the choices and start a new shop", () => {
    show("accepted");
    fireEvent.click(screen.getByRole("button", { name: "Next steps" }));
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect(newSession).toHaveBeenCalledExactlyOnceWith();
    expect(baskets.accept).not.toHaveBeenCalled();
    expect(setView).not.toHaveBeenCalled();
  });

  it("can dismiss and reopen without changing the accepted basket", () => {
    show("accepted");
    fireEvent.click(screen.getByRole("button", { name: "Next steps" }));
    fireEvent.click(screen.getByRole("button", { name: "Close next steps" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Next steps" }));
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true, cancelable: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(newSession).not.toHaveBeenCalled();
  });

  it("keeps new-shop errors visible in the popup for retry", () => {
    show("accepted", "Could not start a new shop. Try again.");
    fireEvent.click(screen.getByRole("button", { name: "Next steps" }));
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Try again");
  });
});
