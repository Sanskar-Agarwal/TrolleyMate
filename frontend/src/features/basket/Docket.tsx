import type { Basket } from "../../api/types";
import { money } from "../../lib/format";

const STATUS: Record<Basket["status"], { label: string; cls: string }> = {
  optimised: { label: "Optimised", cls: "" },
  verified: { label: "Safety-checked", cls: "chip-produce" },
  pending_review: { label: "Awaiting dietitian", cls: "chip-amber" },
  accepted: { label: "Accepted", cls: "chip-produce" },
  superseded: { label: "Replaced", cls: "" },
};

/** The receipt: running total against the budget. */
export default function Docket({ basket, onAccept, busy }: { basket: Basket; onAccept: () => void; busy: boolean }) {
  const budget = basket.budget ?? basket.total;
  const used = budget > 0 ? Math.min(1, basket.total / budget) : 1;
  const withheldValue = basket.items.filter((i) => i.withheld).reduce((s, i) => s + i.line_total, 0);
  const st = STATUS[basket.status];
  const retailers = new Set(basket.items.map((i) => i.retailer.name));
  const nutritionGaps = basket.nutrition != null && !basket.nutrition.adequate; // 1.2.11: met or explicitly accepted

  return (
    <div className="docket-wrap">
      <div className="docket-card">
        <div className="spread">
          <span className="eyebrow">Receipt</span>
          <span className={`chip ${st.cls}`}>{st.label}</span>
        </div>
        <dl className="docket-rows mono">
          <div>
            <dt>Items</dt>
            <dd>{basket.items.filter((i) => !i.withheld).reduce((n, i) => n + i.quantity, 0)} packs</dd>
          </div>
          <div>
            <dt>Stores</dt>
            <dd>{retailers.size}</dd>
          </div>
          {withheldValue > 0 && (
            <div>
              <dt>On hold</dt>
              <dd>+{money(withheldValue)}</dd>
            </div>
          )}
          <div>
            <dt>Budget</dt>
            <dd>{money(basket.budget)}</dd>
          </div>
        </dl>
        <div className="docket-meter" role="meter" aria-valuemin={0} aria-valuemax={budget} aria-valuenow={basket.total} aria-label="Budget used">
          <span style={{ width: `${used * 100}%` }} />
        </div>
        <div className="docket-sum">
          <span className="mono">TOTAL</span>
          <span className="docket-total-figure">{money(basket.total)}</span>
        </div>
        {basket.remaining != null && (
          <p className="small muted mono" style={{ textAlign: "right" }}>
            {basket.remaining >= 0 ? `${money(basket.remaining)} under budget` : `${money(-basket.remaining)} over budget`}
          </p>
        )}
        <button className="btn btn-primary" onClick={onAccept} disabled={busy || basket.status !== "verified" || nutritionGaps}>
          {basket.status === "accepted" ? "Basket accepted" : "Accept basket"}
        </button>
        {basket.status === "pending_review" && <p className="small muted">You can accept once the dietitian has decided.</p>}
        {basket.status === "verified" && nutritionGaps && (
          <p className="small muted">Meet or accept the nutrition gaps below before you accept the basket.</p>
        )}
      </div>
    </div>
  );
}
