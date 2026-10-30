import { useState } from "react";
import type { Goal } from "../../api/types";
import { money } from "../../lib/format";
import { useShop } from "../shop/ShopContext";
import "./basket.css";

export const GOALS: { id: Goal; label: string; blurb: string }[] = [
  { id: "balanced", label: "Balanced", blurb: "A sensible mix of price, nutrition, waste and prep time." },
  { id: "lowest_cost", label: "Lowest cost", blurb: "Lowest basket cost within your confirmed food and dietary requirements." },
  { id: "best_nutrition", label: "Best nutrition", blurb: "More vegetables and protein, chosen for nutrient density." },
  { id: "least_waste", label: "Least waste", blurb: "Fewer excess servings, with perishables prioritised in your meal plan." },
  { id: "fastest_cook", label: "Quickest to cook", blurb: "Ingredients that are fast to prepare on busy nights." },
];

export function GoalRadios({ value, onChange }: { value: Goal; onChange: (g: Goal) => void }) {
  return (
    <div className="goal-grid" role="radiogroup" aria-label="Optimise for">
      {GOALS.map((g) => (
        <button key={g.id} role="radio" aria-checked={value === g.id} className={`goal${value === g.id ? " on" : ""}`} onClick={() => onChange(g.id)}>
          <strong>{g.label}</strong>
          <span className="small muted">{g.blurb}</span>
        </button>
      ))}
    </div>
  );
}

/** Stage 3a: constraints confirmed; choose what to optimise for (1.2.2 goal selector). */
export default function GoalPicker() {
  const { state, build, busy } = useShop();
  const [goal, setGoal] = useState<Goal>(state?.constraints?.payload.goal_hint ?? state?.session.goal ?? "balanced");
  const c = state!.constraints!.payload;
  return (
    <div className="card stack goal-picker">
      <span className="eyebrow">Step 3 · Build your basket</span>
      <h2>What matters most this week?</h2>
      <p className="muted">
        {money(c.budget)} · {c.meals_per_day} meal{c.meals_per_day === 1 ? "" : "s"}/day · {c.days} days · {c.household_size}{" "}
        {c.household_size === 1 ? "person" : "people"}. Allergies and dietary rules apply whichever goal you pick.
      </p>
      <GoalRadios value={goal} onChange={setGoal} />
      <div className="row">
        <button className="btn btn-primary" onClick={() => build(goal)} disabled={!!busy}>
          {busy ? <span className="spinner" /> : null} Build my basket
        </button>
      </div>
    </div>
  );
}
