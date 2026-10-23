import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { preferences } from "../../api/endpoints";
import type { Household, StoredPreference } from "../../api/types";
import PreferencesPanel from "./PreferencesPanel";

vi.mock("../../api/endpoints", () => ({ preferences: { list: vi.fn(), add: vi.fn(), update: vi.fn(), remove: vi.fn() } }));

const household: Household = {
  id: 1, name: "Chen–Taylor household", region: "Sydney Metro", size: 2, members: [], preferences: [],
  mandatory_restrictions: [{ restriction: "tree_nuts", severity: "severe", label: "Tree nuts", members: ["Jamie"] }],
};
const base = { source: "user", match_count: 0, matches: [], blocked: [], hint: null, created_at: "2026-10-22T10:00:00", updated_at: null };
const mushroom: StoredPreference = {
  ...base, id: 1, kind: "dislike", value: "mushroom", label: "Dislike", effect: "avoid", status: "applied",
  matches: ["Button Mushrooms 200g"], match_count: 1,
};
const almondMilk: StoredPreference = {
  ...base, id: 2, kind: "like", value: "almond milk", label: "Like", effect: "favour", status: "overridden",
  blocked: [{ product: "Almond Milk 1L", reason: "Tree nuts (Jamie)" }],
};
const barilla: StoredPreference = {
  ...base, id: 4, kind: "brand", value: "barilla", label: "Preferred brand", effect: "favour", status: "applied",
  matches: ["Penne 500g"], match_count: 1,
};
const peanuts: StoredPreference = {
  ...base, id: 3, kind: "dislike", value: "peanuts", label: "Dislike", effect: "avoid", status: "no_match",
  hint: "Peanuts looks like an allergy or diet. A preference only matches product names; add it to a member's restrictions to have every ingredient checked.",
};
const onChange = vi.fn();

function changed(list: StoredPreference[]) {
  return { household: { ...household, preferences: list.map(({ id, kind, value, source }) => ({ id, kind, value, source })) }, preferences: list, trace: [] };
}

async function show(list: StoredPreference[]) {
  vi.mocked(preferences.list).mockResolvedValue(list);
  render(<PreferencesPanel household={household} onChange={onChange} />);
  if (list.length) await screen.findByText(list[0].value);
  else await screen.findByText("None yet.");
}

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("taste & preference memory (1.2.12)", () => {
  it("shows each remembered preference with what it does, restrictions first", async () => {
    await show([mushroom, almondMilk, barilla, peanuts]);
    expect(screen.getByText("Left out of new baskets: Button Mushrooms 200g.")).toBeTruthy();
    expect(screen.getByText("Picked in a close call: Penne 500g.")).toBeTruthy();
    expect(screen.getByText("Never added: every match breaks a household restriction.")).toBeTruthy();
    expect(screen.getByText("Ruled out: Almond Milk 1L · Tree nuts (Jamie)")).toBeTruthy();
    expect(screen.getByText(/Peanuts looks like an allergy or diet/)).toBeTruthy();
  });

  it("changes a preference in place", async () => {
    const onions = { ...mushroom, value: "onions", matches: ["Brown Onions 1kg"], updated_at: "2026-10-22T11:00:00" };
    vi.mocked(preferences.update).mockResolvedValue(changed([onions]));
    await show([mushroom]);

    fireEvent.click(screen.getByRole("button", { name: "Change Dislike mushroom" }));
    const row = screen.getByRole("listitem");
    fireEvent.change(within(row).getByLabelText("Preference"), { target: { value: " onions " } });
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Left out of new baskets: Brown Onions 1kg.")).toBeTruthy();
    expect(preferences.update).toHaveBeenCalledWith(1, "dislike", "onions");
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ preferences: [expect.objectContaining({ value: "onions" })] }));
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("keeps the editor open and explains why when a change is refused", async () => {
    vi.mocked(preferences.update).mockRejectedValue(new ApiError('You\'ve already saved "like: mushroom". Change or forget that one instead.', 409));
    await show([mushroom]);

    fireEvent.click(screen.getByRole("button", { name: "Change Dislike mushroom" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/already saved "like: mushroom"/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save" })).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("forgets a preference", async () => {
    vi.mocked(preferences.remove).mockResolvedValue(changed([]));
    await show([mushroom]);

    fireEvent.click(screen.getByRole("button", { name: "Forget Dislike mushroom" }));

    expect(await screen.findByText("None yet.")).toBeTruthy();
    expect(preferences.remove).toHaveBeenCalledWith(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ preferences: [] }));
  });

  it("remembers a new preference and clears the box", async () => {
    vi.mocked(preferences.add).mockResolvedValue(changed([mushroom]));
    await show([]);

    fireEvent.change(screen.getByLabelText("Preference"), { target: { value: "  mushroom " } });
    fireEvent.click(screen.getByRole("button", { name: "Remember" }));

    expect(await screen.findByText("mushroom")).toBeTruthy();
    expect(preferences.add).toHaveBeenCalledWith("dislike", "mushroom");
    expect((screen.getByLabelText("Preference") as HTMLInputElement).value).toBe("");
  });
});
