import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mealPlans } from "../../api/endpoints";
import type { Basket, MealPlan, SessionState } from "../../api/types";
import { useShop } from "../shop/ShopContext";
import MealPlanView from "./MealPlanView";

vi.mock("../shop/ShopContext", () => ({ useShop: vi.fn() }));
vi.mock("../../api/endpoints", () => ({ mealPlans: { generate: vi.fn() } }));

const setView = vi.fn();
const run = vi.fn();
const completePlan: MealPlan = {
  id: 7, basket_id: 42, summary: "", requested: 2, planned: 2,
  days: [1, 2].map((day) => ({ day, meals: [{ slot: "Dinner", recipe: "Rice and beans", minutes: 20,
    servings: 2, uses: ["Brown rice", "Kidney beans"] }] })),
  missing: [], reused: ["Brown rice"], leftovers: [], suggested_additions: [],
  assumed_at_home: ["salt", "pepper", "cooking oil"],
};

function show(plan: MealPlan | null = null, status: Basket["status"] = "accepted", busy: string | null = null) {
  vi.mocked(useShop).mockReturnValue({
    state: { basket: { id: 42, status } as Basket, meal_plan: plan } as SessionState,
    busy, run: async (label, action, options) => run(label, action, options), setView,
    trace: [], error: null, negotiation: null, pendingMessage: null, view: "meals",
    focusChat: vi.fn(), clearError: vi.fn(), addTrace: vi.fn(), setBasket: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined), chat: vi.fn().mockResolvedValue(true),
    correct: vi.fn().mockResolvedValue(undefined), clarify: vi.fn().mockResolvedValue(undefined),
    submitForm: vi.fn().mockResolvedValue(undefined), confirm: vi.fn().mockResolvedValue(undefined),
    cancel: vi.fn().mockResolvedValue(undefined), build: vi.fn().mockResolvedValue(undefined),
    negotiate: vi.fn().mockResolvedValue(undefined), cancelNegotiation: vi.fn().mockResolvedValue(undefined), newSession: vi.fn().mockResolvedValue(undefined),
  });
  render(<MealPlanView />);
}

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("accepted-basket meal planning", () => {
  it.each(["verified", "pending_review"] as const)("requires acceptance for a %s basket", (status) => {
    show(null, status);
    expect(screen.queryByRole("button", { name: "Plan my meals" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Review my basket" }));
    expect(setView).toHaveBeenCalledWith("basket");
    expect(mealPlans.generate).not.toHaveBeenCalled();
    if (status === "pending_review") expect(screen.getByText(/waiting for dietary review/)).toBeTruthy();
  });

  it("generates only for the accepted basket", async () => {
    run.mockImplementation(async (_label, action) => action());
    vi.mocked(mealPlans.generate).mockResolvedValue({ meal_plan: completePlan, trace: [] });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Plan my meals" }));
    expect(mealPlans.generate).toHaveBeenCalledExactlyOnceWith(42);
  });

  it("shows complete coverage, pantry assumptions and reused ingredients", () => {
    show(completePlan);
    const status = screen.getByRole("status");
    expect(status.classList.contains("notice-produce")).toBe(true);
    expect(within(status).getByText("Every requested meal is covered.")).toBeTruthy();
    expect(screen.getByText(/Assumed at home: salt, pepper, cooking oil/)).toBeTruthy();
    expect(screen.getByText("Shared across meals:").parentElement?.textContent).toContain("Brown rice");
    expect(screen.queryByText(/Suggested additions/)).toBeNull();
  });

  it("distinguishes an unfilled meal and optional additions from planned food", () => {
    show({ ...completePlan, planned: 1,
      days: [completePlan.days[0], { day: 2, meals: [{ slot: "Dinner", recipe: null, missing: ["veg"] }] }],
      missing: [{ day: 2, slot: "Dinner", suggested_recipe: "Vegetable rice", missing_tags: ["veg"] }],
      suggested_additions: [{ for: "veg", product: "Frozen peas" }],
    });
    expect(screen.getByRole("status").classList.contains("notice-amber")).toBe(true);
    expect(screen.getByText("1 meal still needs ingredients.")).toBeTruthy();
    expect(screen.getByText("Suggested meal: Vegetable rice")).toBeTruthy();
    expect(screen.getByText(/Nothing has been added to your basket/)).toBeTruthy();
    expect(screen.getByText(/Frozen peas/).tagName).toBe("LI");
    expect(mealPlans.generate).not.toHaveBeenCalled();
  });

  it("shows a clear warning when no meals can be planned", () => {
    show({ ...completePlan, planned: 0, reused: [], suggested_additions: [],
      days: [1, 2].map((day) => ({ day, meals: [{ slot: "Dinner", recipe: null, missing: ["veg"] }] })),
      missing: [1, 2].map((day) => ({ day, slot: "Dinner", suggested_recipe: "Vegetable rice", missing_tags: ["veg"] })),
    });
    expect(screen.getByText("2 meals still need ingredients.")).toBeTruthy();
    expect(screen.queryByText("Shared across meals:")).toBeNull();
    expect(screen.queryByText("Every requested meal is covered.")).toBeNull();
  });

  it("explains days with no requested meal in a fractional schedule", () => {
    show({ ...completePlan, requested: 1, planned: 1, days: [completePlan.days[0], { day: 2, meals: [] }] });
    expect(screen.getByText("No meal requested for this day.")).toBeTruthy();
  });

  it.each([null, completePlan])("prevents generation while a plan is being prepared", (plan) => {
    show(plan, "accepted", "Planning meals from your basket");
    const button = screen.getByRole("button", { name: "Planning meals…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(run).not.toHaveBeenCalled();
  });
});
