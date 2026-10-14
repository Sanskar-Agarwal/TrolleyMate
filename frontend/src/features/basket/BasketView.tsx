import { useState } from "react";
import { baskets } from "../../api/endpoints";
import type { BasketItem, Goal } from "../../api/types";
import ShelfTag from "../../components/ShelfTag";
import { GOAL_LABEL, titleCase } from "../../lib/format";
import ComplianceChip from "../compliance/ComplianceChip";
import NutritionPanel from "../compliance/NutritionPanel";
import ExplainDrawer from "../explain/ExplainDrawer";
import { useShop } from "../shop/ShopContext";
import SubstitutionDrawer from "../substitution/SubstitutionDrawer";
import Docket from "./Docket";
import { GoalRadios } from "./GoalPicker";
import "./basket.css";

const ORDER = ["protein", "carb", "veg", "dairy", "fruit", "pantry", "snack"];
const CATEGORY_LABEL: Record<string, string> = {
  protein: "Protein",
  carb: "Grains & starches",
  veg: "Vegetables",
  dairy: "Dairy & alternatives",
  fruit: "Fruit",
  pantry: "Pantry",
  snack: "Snacks",
};

export default function BasketView() {
  const { state, busy, build, run, setBasket } = useShop();
  const basket = state!.basket!;
  const [explain, setExplain] = useState<{ itemId?: number } | null>(null);
  const [swapFor, setSwapFor] = useState<BasketItem | null>(null);
  const [rebuild, setRebuild] = useState(false);
  const [goal, setGoal] = useState<Goal>(basket.goal);

  const groups = ORDER.map((cat) => ({ cat, items: basket.items.filter((i) => i.product.category === cat) })).filter((g) => g.items.length);
  const withheld = basket.items.filter((i) => i.withheld);

  return (
    <div className="basket-layout">
      <div className="stack" style={{ "--gap": "16px" } as React.CSSProperties}>
        <div className="spread">
          <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
            <span className="eyebrow">Your basket · {GOAL_LABEL[basket.goal]}</span>
            <h2>
              {basket.items.length} items for {basket.requirements?.person_meals ?? "?"} meals
            </h2>
          </div>
          <div className="row">
            <button className="btn btn-sm" onClick={() => setExplain({})}>
              Why this basket?
            </button>
            <button className="btn btn-sm" onClick={() => setRebuild((v) => !v)} aria-expanded={rebuild}>
              Change goal
            </button>
          </div>
        </div>

        {basket.summary && <p className="basket-summary">{basket.summary}</p>}

        {rebuild && (
          <div className="card-flat stack">
            <GoalRadios value={goal} onChange={setGoal} />
            <div className="row">
              <button className="btn btn-primary btn-sm" disabled={!!busy} onClick={() => build(goal).then(() => setRebuild(false))}>
                Rebuild as {GOAL_LABEL[goal]}
              </button>
            </div>
          </div>
        )}

        {withheld.length > 0 && (
          <div className="notice notice-amber" role="status">
            <span>
              <strong>Waiting on a dietitian:</strong> {withheld.map((i) => i.product.name).join(", ")}. It's held out of your basket
              and total until a registered dietitian confirms it's safe for your household.
            </span>
          </div>
        )}
        {basket.notifications
          .filter((n) => !n.includes("held until"))
          .map((n) => (
            <div key={n} className="notice">
              {n}
            </div>
          ))}

        {groups.map((g) => (
          <section key={g.cat} className="aisle">
            <h4 className="aisle-head">{CATEGORY_LABEL[g.cat] ?? titleCase(g.cat)}</h4>
            <ul className="items">
              {g.items.map((item) => (
                <li key={item.id} className={`item${item.withheld ? " withheld" : ""}`}>
                  <div className="item-main">
                    <div className="item-name">
                      <strong>{item.product.name}</strong>
                      {item.quantity > 1 && <span className="qty mono">×{item.quantity}</span>}
                    </div>
                    <div className="row small muted" style={{ "--gap": "8px" } as React.CSSProperties}>
                      <span>{item.retailer.name}</span>
                      {item.product.brand && <span>· {item.product.brand}</span>}
                      <ComplianceChip status={item.compliance} withheld={item.withheld} />
                    </div>
                    <div className="row item-actions" style={{ "--gap": "4px" } as React.CSSProperties}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setExplain({ itemId: item.id })}>
                        Why this?
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => setSwapFor(item)} disabled={!!busy}>
                        Find a substitute
                      </button>
                    </div>
                  </div>
                  <ShelfTag price={item.pack_price} unit={item.unit_price_label} special={item.on_special} muted={item.withheld} />
                </li>
              ))}
            </ul>
          </section>
        ))}

        {basket.excluded.length > 0 && (
          <details className="excluded">
            <summary className="small">
              {basket.excluded.length} product{basket.excluded.length === 1 ? "" : "s"} left out for safety
            </summary>
            <ul className="small">
              {basket.excluded.map((e) => (
                <li key={e.product}>
                  <strong>{e.product}</strong> — {e.findings[0]?.detail}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="stack basket-side" style={{ "--gap": "16px" } as React.CSSProperties}>
        <Docket
          basket={basket}
          onAccept={() => run("Accepting basket", () => baskets.accept(basket.id)).then((r) => r && setBasket(r.basket))}
          busy={!!busy}
        />
        {basket.nutrition && <NutritionPanel nutrition={basket.nutrition} />}
      </div>

      {explain && <ExplainDrawer basketId={basket.id} itemId={explain.itemId} onClose={() => setExplain(null)} />}
      {swapFor && <SubstitutionDrawer item={swapFor} onClose={() => setSwapFor(null)} />}
    </div>
  );
}
