import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { households } from "../../api/endpoints";
import type { IntakeState, SessionState } from "../../api/types";
import { useShop } from "../shop/ShopContext";
import ConstraintCard from "./ConstraintCard";

vi.mock("../shop/ShopContext", () => ({ useShop: vi.fn() }));
vi.mock("../../api/endpoints", () => ({ households: { vocabulary: vi.fn() } }));

const locked = { restriction: "tree_nuts", label: "Tree nuts", severity: "severe", locked: true, members: ["Jamie"] };
const vocabulary = [
  { id: "tree_nuts", label: "Tree nuts", kind: "allergy" },
  { id: "lactose", label: "Lactose", kind: "intolerance" },
  { id: "egg", label: "Egg", kind: "allergy" },
];
let shop: ReturnType<typeof useShop>;

function intake(patch: Partial<IntakeState> = {}): IntakeState {
  return {
    request_id: 7, raw_text: "$100 for a week, two meals per day for two people",
    status: "draft", stage: "awaiting_confirmation", mode: "text", correction_count: 0, max_corrections: 3,
    draft: { budget: 100, household_size: 2, meals_per_day: 2, days: 7,
      restrictions: [locked, { restriction: "lactose", label: "Lactose", severity: "moderate" }],
      preferences: ["dislike:mushroom"], nutritional_targets: [] },
    questions: [], missing_fields: [], assumptions: [], ...patch,
  };
}

function setIntake(value: IntakeState) {
  shop.state = { ...shop.state, intake: value } as SessionState;
}

async function show(value = intake()) {
  setIntake(value);
  const view = render(<ConstraintCard />);
  await screen.findByRole("option", { name: "Egg" });
  return view;
}

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;
const change = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(households.vocabulary).mockResolvedValue(vocabulary);
  shop = {
    canCancelBuild: false, cancellingBuild: false, cancelBuild: vi.fn().mockResolvedValue(undefined),
    state: null, busy: null, trace: [], error: null, negotiation: null, pendingMessage: null, view: "basket",
    setView: vi.fn(), focusChat: vi.fn(), clearError: vi.fn(), addTrace: vi.fn(), setBasket: vi.fn(),
    run: vi.fn().mockResolvedValue(undefined), refresh: vi.fn().mockResolvedValue(undefined),
    chat: vi.fn().mockResolvedValue(true), correct: vi.fn().mockResolvedValue(undefined),
    clarify: vi.fn().mockResolvedValue(undefined), submitForm: vi.fn().mockResolvedValue(undefined),
    confirm: vi.fn().mockResolvedValue(undefined), cancel: vi.fn().mockResolvedValue(undefined),
    build: vi.fn().mockResolvedValue(undefined), negotiate: vi.fn().mockResolvedValue(undefined), cancelNegotiation: vi.fn().mockResolvedValue(undefined),
    newSession: vi.fn().mockResolvedValue(undefined),
  };
  vi.mocked(useShop).mockImplementation(() => shop);
});
afterEach(cleanup);

describe("intake dietary corrections", () => {
  it("saves added, removed and revised request restrictions while keeping household rules locked", async () => {
    await show(intake({ mode: "form", stage: "awaiting_form" }));
    expect(screen.queryByRole("button", { name: "Remove Tree nuts restriction" })).toBeNull();
    expect(screen.queryByLabelText("Tree nuts severity")).toBeNull();
    expect(screen.queryByRole("option", { name: "Tree nuts" })).toBeNull();
    expect(screen.getByText(/Required by your household \(Jamie\)/)).toBeTruthy();
    fireEvent.click(button("Remove Lactose restriction"));
    change("Add dietary restriction", "egg");
    fireEvent.click(button("Add restriction"));
    change("Egg severity", "mild");
    expect(button("Confirm constraints").disabled).toBe(true);
    fireEvent.click(button("Save form"));
    expect(shop.submitForm).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      restrictions: [{ restriction: "tree_nuts", severity: "severe" }, { restriction: "egg", severity: "mild" }],
    }));
    expect(shop.confirm).not.toHaveBeenCalled();
  });

  it("edits preferences and rejects empty rows before saving", async () => {
    await show(intake({ mode: "form" }));
    change("Preference 1 type", "avoid_brand");
    change("Preference 1 value", "  Example Brand  ");
    fireEvent.click(button("Add preference"));
    expect(button("Save form").disabled).toBe(true);
    expect(button("Confirm constraints").disabled).toBe(true);
    expect(screen.getByLabelText("Preference 2 value").getAttribute("aria-invalid")).toBe("true");
    change("Preference 2 type", "like");
    change("Preference 2 value", "tomato");
    fireEvent.click(button("Save form"));
    expect(shop.submitForm).toHaveBeenCalledWith(expect.objectContaining({ preferences: ["avoid_brand:Example Brand", "like:tomato"] }));
  });

  it("can explicitly clear all soft preferences", async () => {
    await show();
    fireEvent.click(button("Remove preference 1"));
    fireEvent.click(button("Apply correction"));
    expect(shop.correct).toHaveBeenCalledExactlyOnceWith({ preferences: [] });
  });

  it("does not send unchanged optional targets when correcting the budget", async () => {
    await show(intake({ questions: [{ field: "nutritional_targets", question: "How much protein?" }] }));
    change("Budget in dollars", "80");
    fireEvent.click(button("Apply correction"));
    expect(shop.correct).toHaveBeenCalledExactlyOnceWith({ budget: 80 });
    expect(button("Confirm constraints").disabled).toBe(true);
  });

  it.each(["text", "form"] as const)("declines an optional protein target through clarification in %s mode", async (mode) => {
    await show(intake({ mode, questions: [{ field: "nutritional_targets", question: "How much protein?" }] }));
    fireEvent.click(button("No extra protein target"));
    expect(shop.clarify).toHaveBeenCalledExactlyOnceWith("No target");
    expect(shop.correct).not.toHaveBeenCalled();
    expect(shop.submitForm).not.toHaveBeenCalled();
  });

  it("requires unsupported legacy preferences to be corrected or removed", async () => {
    const value = intake();
    value.draft.preferences = ["organic food"];
    await show(value);
    expect(button("Confirm constraints").disabled).toBe(true);
    change("Budget in dollars", "80");
    expect(button("Apply correction").disabled).toBe(true);
    change("Preference 1 type", "like");
    expect(button("Apply correction").disabled).toBe(false);
    fireEvent.click(button("Apply correction"));
    expect(shop.correct).toHaveBeenCalledWith({ budget: 80, preferences: ["like:organic food"] });
  });

  it("keeps other nutrition targets when protein is revised", async () => {
    const value = intake();
    value.draft.nutritional_targets = [{ nutrient: "fibre_g", minimum_per_day: 30 }, { nutrient: "protein_g", minimum_per_day: 60 }];
    await show(value);
    change(/Protein/, "75");
    fireEvent.click(button("Apply correction"));
    expect(shop.correct).toHaveBeenCalledWith({ nutritional_targets: [
      { nutrient: "fibre_g", minimum_per_day: 30 }, { nutrient: "protein_g", minimum_per_day: 75 },
    ] });
  });

  it.each([
    ["Budget in dollars", "NaN"], ["Budget in dollars", "0"], [/People/, "1.5"], [/People/, "21"],
    [/Days/, "32"], [/Days/, "1.5"], [/Meals/, "5.1"], [/Protein/, "-2"],
  ])("blocks invalid %s values (%s)", async (label, value) => {
    await show();
    change(label, value);
    expect(button("Apply correction").disabled).toBe(true);
    expect(button("Confirm constraints").disabled).toBe(true);
    fireEvent.click(button("Apply correction"));
    expect(shop.correct).not.toHaveBeenCalled();
  });

  it("requires the reviewed form to be saved even when its prefilled values are unchanged", async () => {
    await show(intake({ mode: "form", stage: "awaiting_form" }));
    expect(button("Save form").disabled).toBe(false);
    expect(button("Confirm constraints").disabled).toBe(true);
    fireEvent.click(button("Save form"));
    expect(shop.submitForm).toHaveBeenCalledWith(expect.objectContaining({ budget: 100, restrictions: expect.any(Array), preferences: ["dislike:mushroom"] }));
  });

  it("preserves unsaved fields across unrelated server updates and resets them for a new request", async () => {
    const value = intake();
    const view = await show(value);
    change("Budget in dollars", "80");
    change("Preference 1 value", "onion");
    setIntake({ ...value, draft: { ...value.draft, days: 8 } });
    view.rerender(<ConstraintCard />);
    expect((screen.getByLabelText("Budget in dollars") as HTMLInputElement).value).toBe("80");
    expect((screen.getByLabelText("Preference 1 value") as HTMLInputElement).value).toBe("onion");
    expect((screen.getByLabelText(/Days/) as HTMLInputElement).value).toBe("8");
    setIntake({ ...value, request_id: 8, draft: { ...value.draft, budget: 50, preferences: ["like:apple"] } });
    view.rerender(<ConstraintCard />);
    await waitFor(() => expect((screen.getByLabelText("Budget in dollars") as HTMLInputElement).value).toBe("50"));
    expect((screen.getByLabelText("Preference 1 value") as HTMLInputElement).value).toBe("apple");
    expect(button("Confirm constraints").disabled).toBe(false);
  });

  it("keeps corrections dirty until the server returns the saved draft", async () => {
    const value = intake();
    const view = await show(value);
    change("Preference 1 value", "onion");
    fireEvent.click(button("Apply correction"));
    expect(button("Confirm constraints").disabled).toBe(true);
    setIntake({ ...value, draft: { ...value.draft, preferences: ["dislike:onion"] } });
    view.rerender(<ConstraintCard />);
    await waitFor(() => expect(button("Confirm constraints").disabled).toBe(false));
    fireEvent.click(button("Confirm constraints"));
    expect(shop.confirm).toHaveBeenCalledOnce();
  });

  it("retains an unanswered clarification after a failed request and blocks repeat submission while busy", async () => {
    const view = await show(intake({ questions: [{ field: "nutritional_targets", question: "How much protein?" }] }));
    change("Your answer", "60 grams");
    fireEvent.click(button("Answer"));
    await waitFor(() => expect(shop.clarify).toHaveBeenCalledOnce());
    expect((screen.getByLabelText("Your answer") as HTMLInputElement).value).toBe("60 grams");
    shop.busy = "Updating your request";
    view.rerender(<ConstraintCard />);
    fireEvent.submit(screen.getByLabelText("Your answer").closest("form")!);
    expect(shop.clarify).toHaveBeenCalledOnce();
  });

  it("clears the previous answer when the server moves to a different clarification", async () => {
    const value = intake({ questions: [{ field: "nutritional_targets", question: "How much protein?" }] });
    const view = await show(value);
    change("Your answer", "60 grams");
    setIntake({ ...value, questions: [{ field: "days", question: "How many days?" }] });
    view.rerender(<ConstraintCard />);
    expect((screen.getByLabelText("Your answer") as HTMLInputElement).value).toBe("");
  });

  it("allows retry when restriction choices fail to load", async () => {
    vi.mocked(households.vocabulary).mockRejectedValueOnce(new Error("offline"));
    setIntake(intake());
    render(<ConstraintCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry dietary choices" }));
    expect(await screen.findByRole("option", { name: "Egg" })).toBeTruthy();
  });
});
