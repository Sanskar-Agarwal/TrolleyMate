import { useState } from "react";
import { pricing } from "../../api/endpoints";
import { money } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";
import { useShop } from "../shop/ShopContext";
import "./pricing.css";

/** UC-05 — the basket priced at every retailer and as a split basket, against a named baseline. */
export default function PriceComparison() {
  const { state, addTrace } = useShop();
  const basketId = state!.basket!.id;
  const [baseline, setBaseline] = useState<number | undefined>(undefined);
  const { data, error, loading } = useLoad(async () => {
    const { trace, ...c } = await pricing.compare(basketId, baseline);
    addTrace(trace);
    return c;
  }, `${basketId}:${baseline ?? "default"}`);

  if (error) return <div className="notice notice-beet">{error}</div>;
  if (!data) return <p className="row muted"><span className="spinner" /> Pricing your basket at every store…</p>;

  const maxTotal = Math.max(...data.options.map((o) => o.total));
  return (
    <div className="stack pricing" style={{ "--gap": "18px" } as React.CSSProperties}>
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">AI Market Analyst · compare stores</span>
          <h2>{data.cheapest ? `${data.cheapest.name} saves ${money(data.cheapest.saving)}` : "Comparison incomplete"}</h2>
        </div>
        <label className="row small">
          Compare against
          <select className="input" style={{ width: "auto" }} value={data.baseline.id} onChange={(e) => setBaseline(Number(e.target.value))} disabled={loading}>
            {data.retailers.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {data.insight && <p className="basket-summary">{data.insight}</p>}

      <div className="compare-bars">
        {data.options.map((o) => (
          <div key={o.name} className={`compare-row${o === data.cheapest || o.name === data.cheapest?.name ? " best" : ""}`}>
            <span className="compare-name">
              <strong>{o.name}</strong>
              {o.name === data.baseline.name && <span className="chip">baseline</span>}
              {!o.complete && <span className="chip chip-amber">{o.unpriced.length} unpriced</span>}
            </span>
            <span className="compare-bar">
              <span style={{ width: `${(o.total / maxTotal) * 100}%` }} />
            </span>
            <span className="mono compare-total">{money(o.total)}</span>
            <span className={`mono small ${o.saving > 0 ? "saving" : "muted"}`}>
              {o.saving > 0 ? `−${money(o.saving)} (${o.saving_pct}%)` : o.saving < 0 ? `+${money(-o.saving)}` : "—"}
            </span>
          </div>
        ))}
      </div>

      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th>Item</th>
              {data.retailers.map((r) => (
                <th key={r.id}>{r.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.item_id}>
                <td>
                  {row.product}
                  {row.quantity > 1 && <span className="mono muted"> ×{row.quantity}</span>}
                </td>
                {data.retailers.map((r) => {
                  const p = row.prices[r.id];
                  return (
                    <td key={r.id} className={`mono${row.cheapest_retailer_id === r.id ? " cheapest" : ""}`}>
                      {p ? (
                        <>
                          {money(p.line)}
                          {p.on_special && <span className="chip chip-beet" style={{ marginLeft: 6 }}>special</span>}
                          {p.unit_price != null && (
                            <div className="muted" style={{ fontSize: "0.7rem" }}>
                              {money(p.unit_price)}/{p.unit_basis === "each" ? "ea" : p.unit_basis}
                            </div>
                          )}
                        </>
                      ) : (
                        <span className="muted">no price</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.refreshed_quotes > 0 && <p className="small muted">Refreshed {data.refreshed_quotes} out-of-date price{data.refreshed_quotes === 1 ? "" : "s"} for this comparison.</p>}
    </div>
  );
}
