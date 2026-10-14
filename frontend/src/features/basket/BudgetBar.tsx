import { money } from "../../lib/format";
import { useShop } from "../shop/ShopContext";

/** Always-visible spend against budget, pinned to the top of the workspace. */
export default function BudgetBar() {
  const { state, setView } = useShop();
  const b = state!.basket!;
  const budget = b.budget ?? b.total;
  const used = budget > 0 ? b.total / budget : 1;
  const over = b.remaining != null && b.remaining < 0;
  const held = b.items.filter((i) => i.withheld).length;

  return (
    <div className="budget-bar" role="group" aria-label="Budget">
      <div className="budget-figures">
        <span className="budget-spent">{money(b.total)}</span>
        <span className="muted small">of {money(b.budget)}</span>
      </div>
      <div
        className={`budget-meter${over ? " over" : ""}`}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={budget}
        aria-valuenow={b.total}
        aria-label={`${Math.round(used * 100)}% of budget used`}
      >
        <span style={{ width: `${Math.min(used, 1) * 100}%` }} />
      </div>
      <span className={`chip ${over ? "chip-beet" : "chip-produce"}`}>
        {over ? `${money(-b.remaining!)} over` : `${money(b.remaining)} left`}
      </span>
      {held > 0 && (
        <button className="chip chip-amber" onClick={() => setView("basket")}>
          {held} on hold
        </button>
      )}
    </div>
  );
}
