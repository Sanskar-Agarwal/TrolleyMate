import BuyTimingPanel from "../buytiming/BuyTimingPanel";
import MealPlanView from "../mealplan/MealPlanView";
import PriceComparison from "../pricing/PriceComparison";
import { type ShopView, useShop } from "../shop/ShopContext";
import BasketView from "./BasketView";

const TABS: { id: ShopView; label: string }[] = [
  { id: "basket", label: "Basket" },
  { id: "prices", label: "Compare stores" },
  { id: "meals", label: "Meal plan" },
  { id: "timing", label: "When to buy" },
];

/** Stage 3/4: the basket and everything you can do with it. Each tab is owned by a different feature. */
export default function BasketWorkspace() {
  const { view, setView } = useShop();
  return (
    <div className="stack" style={{ "--gap": "16px" } as React.CSSProperties}>
      <div className="tabs" role="tablist" aria-label="Basket views">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={view === t.id} className="tab" onClick={() => setView(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {view === "basket" && <BasketView />}
      {view === "prices" && <PriceComparison />}
      {view === "meals" && <MealPlanView />}
      {view === "timing" && <BuyTimingPanel />}
    </div>
  );
}
