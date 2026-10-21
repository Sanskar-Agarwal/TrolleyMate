import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { compliance } from "../../api/endpoints";
import type { Basket, Nutrition } from "../../api/types";
import { useShop } from "../shop/ShopContext";
import NutritionPanel from "./NutritionPanel";

vi.mock("../shop/ShopContext", () => ({ useShop: vi.fn() }));
vi.mock("../../api/endpoints", () => ({ compliance: { nutrition: vi.fn(), acceptGap: vi.fn() } }));

const setBasket = vi.fn();
const required = { kcal: 7700, protein_g: 308, veg_serves: 28, staple_serves: 14 };
const met = (k: keyof typeof required) => ({ nutrient: k, required: required[k], provided: required[k], coverage_pct: 100, met: true });

const adequate: Nutrition = {
  adequate: true, provided: { ...required }, required, gaps: [], suggestions: [], targets: "prototype-2026-10",
  coverage: (Object.keys(required) as (keyof typeof required)[]).map(met), exceptions: [],
};
const vegGap: Nutrition = {
  ...adequate,
  adequate: false,
  provided: { ...required, veg_serves: 16 },
  coverage: [met("kcal"), met("protein_g"), { nutrient: "veg_serves", required: 28, provided: 16, coverage_pct: 57, met: false }, met("staple_serves")],
  gaps: [{ nutrient: "veg_serves", required: 28, provided: 16, short_by: 12 }],
  suggestions: ["Add a bag of frozen mixed vegetables or fresh greens."],
};
const vegAccepted: Nutrition = {
  ...vegGap,
  adequate: true,
  coverage: vegGap.coverage!.map((c) => (c.nutrient === "veg_serves" ? { ...c, accepted: true } : c)),
  exceptions: [{ nutrient: "veg_serves", short_by: 12, accepted_by: "Riley Brooks", accepted_by_id: 2, accepted_at: "2026-10-21T10:00:00", note: "We grow our own" }],
};

function show(nutrition: Nutrition) {
  vi.mocked(useShop).mockReturnValue({
    state: { basket: { id: 42 } as Basket },
    busy: null,
    run: async (_label: string, action: () => Promise<unknown>) => action(),
    setBasket,
  } as unknown as ReturnType<typeof useShop>);
  render(<NutritionPanel nutrition={nutrition} />);
}

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("nutrition coverage (1.2.11)", () => {
  it("shows staples alongside the other targets and asks nothing of an adequate basket", () => {
    show(adequate);
    expect(screen.getByText("Adequate")).toBeTruthy();
    expect(screen.getByText("Staples")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /OK with this gap/ })).toBeNull();
    expect(compliance.nutrition).not.toHaveBeenCalled();
  });

  it("lists candidate repairs for a gap and records an explicit acceptance with its reason", async () => {
    vi.mocked(compliance.nutrition).mockResolvedValue({
      nutrition: vegGap, trace: [],
      repairs: [{ nutrient: "veg_serves", product_id: 9, product: "Frozen Mixed Veg 1kg", quantity: 2, adds: 16, closes_gap: true,
        cost: 6, retailer: "Coles", within_budget: true }],
    });
    vi.mocked(compliance.acceptGap).mockResolvedValue({ basket: { id: 42, nutrition: vegAccepted } as Basket, trace: [] });
    show(vegGap);

    expect(screen.getByText("Gaps found")).toBeTruthy();
    expect(await screen.findByText(/Add 2 × Frozen Mixed Veg 1kg/)).toBeTruthy();
    expect(compliance.acceptGap).not.toHaveBeenCalled(); // nothing is accepted without the shopper asking

    fireEvent.click(screen.getByRole("button", { name: /OK with this gap/ }));
    fireEvent.change(screen.getByLabelText(/Why is this gap OK/), { target: { value: "We grow our own " } });
    fireEvent.click(screen.getByRole("button", { name: "Accept the veg serves gap" }));

    await vi.waitFor(() => expect(setBasket).toHaveBeenCalledWith(expect.objectContaining({ id: 42 })));
    expect(compliance.acceptGap).toHaveBeenCalledWith(42, ["veg_serves"], "We grow our own");
  });

  it("shows an accepted gap as an exception, with who accepted it and why", () => {
    show(vegAccepted);
    expect(screen.getByText("Adequate with exception")).toBeTruthy();
    expect(screen.getByText(/You accepted veg serves short by 12: "We grow our own" \(Riley Brooks/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /OK with this gap/ })).toBeNull();
  });
});
