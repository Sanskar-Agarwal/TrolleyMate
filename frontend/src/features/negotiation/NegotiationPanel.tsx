import { useState } from "react";
import { money } from "../../lib/format";
import { useShop } from "../shop/ShopContext";
import "./negotiation.css";

/** UC-03: "Stretch my budget": the request can't be met; offer trade-offs, never on safety. */
export default function NegotiationPanel() {
  const { negotiation, negotiate, cancelNegotiation, busy, state } = useShop();
  const n = negotiation!;
  const c = state?.constraints?.payload;
  const [budget, setBudget] = useState(String(c?.budget ?? n.budget ?? ""));
  const [days, setDays] = useState(String(c?.days ?? n.days ?? ""));

  return (
    <div className="card stack negotiation">
      <span className="eyebrow">Can't fit everything</span>
      <h2>Let's find a trade-off</h2>
      <p style={{ fontSize: "var(--step-1)" }}>{n.message}</p>

      {n.options.length > 0 && (
        <div className="options">
          {n.options.map((o) => (
            <button
              key={o.id}
              className="option"
              disabled={!!busy}
              onClick={() => negotiate({ option_id: o.id, budget: o.budget, days: o.days, meal_count: o.meal_count })}
            >
              <span className="eyebrow">{o.id === "increase_budget" ? "Spend a little more" : "Cover fewer meals"}</span>
              <strong>{o.label}</strong>
              <span className="small muted">{o.detail}</span>
            </button>
          ))}
        </div>
      )}

      <form
        className="row custom"
        onSubmit={(e) => {
          e.preventDefault();
          void negotiate({ budget: Number(budget) || undefined, days: Number(days) || undefined });
        }}
      >
        <span className="small muted">Or set your own:</span>
        <label className="row small" style={{ "--gap": "4px" } as React.CSSProperties}>
          Budget $<input className="input mono" style={{ width: 90 }} value={budget} onChange={(e) => setBudget(e.target.value)} inputMode="decimal" />
        </label>
        <label className="row small" style={{ "--gap": "4px" } as React.CSSProperties}>
          Days <input className="input mono" style={{ width: 64 }} value={days} onChange={(e) => setDays(e.target.value)} inputMode="numeric" />
        </label>
        <button className="btn btn-sm" disabled={!!busy}>
          Try again
        </button>
      </form>
      {n.shortfall != null && <p className="small muted mono">Shortfall at current settings: {money(n.shortfall)}</p>}
      {n.timed_out && <p className="small muted">The search hit its time limit, so an option may be missing.</p>}
      <div className="row">
        <button className="btn btn-ghost btn-sm" onClick={() => void cancelNegotiation()} disabled={!!busy}>
          Keep my request as it is
        </button>
      </div>
      <p className="small muted">Allergies and dietary restrictions are never part of the trade-off.</p>
    </div>
  );
}
