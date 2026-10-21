import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Basket, Nutrition } from "../../api/types";
import Docket from "./Docket";

afterEach(cleanup);

const nutrition = (adequate: boolean) => ({ adequate, provided: {}, required: {}, gaps: [], suggestions: [] }) as Nutrition;
const basket = (status: Basket["status"], n: Nutrition | null) =>
  ({ id: 42, status, items: [], total: 60, budget: 70, remaining: 10, nutrition: n }) as unknown as Basket;

describe("accepting a basket (1.2.11 gate)", () => {
  it("holds a safety-checked basket back while a nutrition gap is open", () => {
    const onAccept = vi.fn();
    render(<Docket basket={basket("verified", nutrition(false))} onAccept={onAccept} busy={false} />);
    const button = screen.getByRole("button", { name: "Accept basket" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/Meet or accept the nutrition gaps below/)).toBeTruthy();
  });

  it("lets it through once every gap is met or explicitly accepted", () => {
    const onAccept = vi.fn();
    render(<Docket basket={basket("verified", nutrition(true))} onAccept={onAccept} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Accept basket" }));
    expect(onAccept).toHaveBeenCalled();
    expect(screen.queryByText(/nutrition gaps/)).toBeNull();
  });

  it("keeps the dietitian message for a basket awaiting review", () => {
    render(<Docket basket={basket("pending_review", nutrition(false))} onAccept={vi.fn()} busy={false} />);
    expect(screen.getByText(/once the dietitian has decided/)).toBeTruthy();
    expect(screen.queryByText(/nutrition gaps/)).toBeNull();
  });
});
