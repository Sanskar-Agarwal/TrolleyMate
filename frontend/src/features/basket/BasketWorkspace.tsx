import { useState } from "react";
import BuyTimingPanel from "../buytiming/BuyTimingPanel";
import MealPlanView from "../mealplan/MealPlanView";
import PriceComparison from "../pricing/PriceComparison";
import BasketView from "./BasketView";

const TABS = [
  { id: "basket", label: "Basket" },
  { id: "prices", label: "Compare stores" },
  { id: "meals", label: "Meal plan" },
  { id: "timing", label: "When to buy" },
] as const;

type Tab = (typeof TABS)[number]["id"];

/** Stage 3b/4 — the basket and everything you can do with it. Each tab is owned by a different feature. */
export default function BasketWorkspace() {
  const [tab, setTab] = useState<Tab>("basket");
  return (
    <div className="stack" style={{ "--gap": "16px" } as React.CSSProperties}>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "basket" && <BasketView />}
      {tab === "prices" && <PriceComparison />}
      {tab === "meals" && <MealPlanView />}
      {tab === "timing" && <BuyTimingPanel />}
    </div>
  );
}
