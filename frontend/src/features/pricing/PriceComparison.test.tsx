import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Comparison } from "../../api/types";
import PriceComparison from "./PriceComparison";
import { pricing } from "../../api/endpoints";

afterEach(cleanup);

const comparison: Comparison = {
  basket_id: 7,
  baseline: { id: 1, name: "GreenGrocer Express", total: 20 },
  options: [
    { name: "GreenGrocer Express", retailer_id: 1, total: 20, saving: 0, saving_pct: 0, complete: true, unpriced: [], is_split: false },
    { name: "Harvest Market", retailer_id: 4, total: 18, saving: 2, saving_pct: 10, complete: true, unpriced: [], is_split: false },
    { name: "Split basket (cheapest per item)", retailer_id: null, total: 15, saving: 5, saving_pct: 25, complete: true, unpriced: [], is_split: true },
  ],
  rows: [],
  retailers: [
    { id: 1, name: "GreenGrocer Express", source: "catalogue" },
    { id: 2, name: "ValueMart", source: "catalogue" },
    { id: 3, name: "FreshCo", source: "partner_api" },
    { id: 4, name: "Harvest Market", source: "catalogue" },
  ],
  split_plan: [
    { retailer_id: 2, name: "ValueMart", subtotal: 6, items: [{ item_id: 1, product: "Brown Rice 1kg", quantity: 2, line: 6, on_special: false, saves_vs_next: 0.8 }] },
    { retailer_id: 4, name: "Harvest Market", subtotal: 9, items: [{ item_id: 2, product: "Turkey Mince 500g", quantity: 1, line: 9, on_special: true, saves_vs_next: 0 }] },
  ],
  cheapest: null,
  insight: null,
  complete: true,
  refreshed_quotes: 0,
};
comparison.cheapest = comparison.options[2];

vi.mock("../shop/ShopContext", () => ({ useShop: () => ({ state: { basket: { id: 7 } }, addTrace: vi.fn() }) }));
vi.mock("../../api/endpoints", () => ({ pricing: { compare: vi.fn(async () => ({ ...comparison, trace: [] })) } }));

describe("cheapest from each store (UC-05)", () => {
  it("groups the split basket by the store each item is cheapest at", async () => {
    render(<PriceComparison />);
    expect(await screen.findByText(/Cheapest from each store · 4 stores compared/)).toBeTruthy();
    const valueMart = screen.getByText("Brown Rice 1kg").closest(".split-store") as HTMLElement;
    expect(within(valueMart).getByText("ValueMart")).toBeTruthy();
    expect(within(valueMart).getByText("−$0.80")).toBeTruthy();
    const harvest = screen.getByText("Turkey Mince 500g").closest(".split-store") as HTMLElement;
    expect(within(harvest).getByText("special")).toBeTruthy();
  });
});


it("does not advertise savings when the baseline is incomplete", async () => {
  const options = comparison.options.map((o, i) => ({ ...o, saving: null, saving_pct: null,
    complete: i !== 0, unpriced: i === 0 ? ["Brown Rice 1kg"] : [] }));
  vi.mocked(pricing.compare).mockResolvedValueOnce({ ...comparison, options, cheapest: options[2], trace: [] });
  render(<PriceComparison />);
  expect(await screen.findByText(/has the lowest complete total/)).toBeTruthy();
  expect(screen.getAllByText("Savings unavailable")).toHaveLength(2);
  expect(screen.getByText("$20.00 (partial)")).toBeTruthy();
  expect(screen.queryByText(/saves \$5/)).toBeNull();
});
