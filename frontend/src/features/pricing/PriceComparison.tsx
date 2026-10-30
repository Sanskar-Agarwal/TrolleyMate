import { useState } from "react";
import { pricing } from "../../api/endpoints";
import Skeleton from "../../components/Skeleton";
import { money } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";
import { useShop } from "../shop/ShopContext";
import "./pricing.css";

/** UC-05: the basket priced at every retailer and as a split basket, against a named baseline. */
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
  if (!data) return <Skeleton rows={5} height={26} label="Pricing your basket at every store" />;

  const sortedOptions = [...data.options].sort((a, b) =>
    a.name === data.baseline.name ? -1 : b.name === data.baseline.name ? 1 : 0
  );
  const maxTotal = Math.max(...data.options.map((o) => o.total));
  return (
    <div className="stack pricing" style={{ "--gap": "18px" } as React.CSSProperties}>
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">AI Market Analyst · compare stores</span>
          <h2>{data.cheapest ? (data.cheapest.saving == null ? `${data.cheapest.name} has the lowest complete total` : `${data.cheapest.name} saves ${money(data.cheapest.saving)}`) : "Comparison incomplete"}</h2>
        </div>
        <p className="small muted" style={{ marginTop: 2 }}>Click a store row to compare against it</p>
      </div>

      {data.insight && <p className="basket-summary">{data.insight}</p>}

      <div className="compare-bars">
        {sortedOptions.map((o) => (
          <div
            key={o.name}
            className={`compare-row${o === data.cheapest || o.name === data.cheapest?.name ? " best" : ""}${!o.is_split ? " clickable" : ""}${o.name === data.baseline.name ? " is-baseline" : ""}${loading ? " loading" : ""}`}
            role={!o.is_split ? "button" : undefined}
            tabIndex={!o.is_split && !loading ? 0 : -1}
            onClick={() => { if (!loading && !o.is_split && o.retailer_id != null) setBaseline(o.retailer_id); }}
            onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !o.is_split && o.retailer_id != null) setBaseline(o.retailer_id); }}
          >
            <span className="compare-name">
              <strong>{o.name}</strong>
              {!o.complete && <span className="chip chip-amber">{o.unpriced.length} unpriced</span>}
            </span>
            <span className="compare-bar">
              <span style={{ width: `${(maxTotal ? o.total / maxTotal : 0) * 100}%` }} />
            </span>
            <span className="mono compare-total">{money(o.total)}{!o.complete && " (partial)"}</span>
            {o.name === data.baseline.name
              ? <span className="compare-saving-wrap"><span className="chip">baseline</span></span>
              : <span className="compare-saving-wrap">
                  <span className={`mono small saving-amount ${o.saving != null && o.saving > 0 ? "saving" : "muted"}`}>
                    {o.saving == null ? "Savings unavailable" : o.saving > 0 ? `save ${money(o.saving)} (${o.saving_pct}%)` : `extra ${money(-o.saving)}`}
                  </span>
                  {!o.is_split && <span className="chip chip-use-baseline">Use as baseline</span>}
                </span>
            }
          </div>
        ))}
      </div>

      {data.split_plan.length > 0 && (
        <div className="stack" style={{ "--gap": "10px" } as React.CSSProperties}>
          <span className="eyebrow">Cheapest from each store · {data.retailers.length} stores compared</span>
          <p className="small muted">Each item is listed under the store that sells it cheapest, with how much less it is than the next-cheapest store.</p>
          <div className="split-plan">
            {data.split_plan.map((store) => (
              <div key={store.retailer_id} className="split-store">
                <div className="spread">
                  <strong>{store.name}</strong>
                  <span className="mono">{money(store.subtotal)}</span>
                </div>
                <ul>
                  {store.items.map((i) => (
                    <li key={i.item_id} className="small">
                      <span>
                        {i.product}
                        {i.quantity > 1 && <span className="mono muted"> ×{i.quantity}</span>}
                        {i.on_special && <span className="chip chip-beet" style={{ marginLeft: 6 }}>special</span>}
                      </span>
                      {i.saves_vs_next > 0 && <span className="mono saving split-saving" title="Cheaper than the next-cheapest store by this much">−{money(i.saves_vs_next)}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

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
                          {p.unit_price != null ? (
                            <div className="muted" style={{ fontSize: "0.7rem" }}>
                              {money(p.unit_price)}/{p.unit_basis === "each" ? "ea" : p.unit_basis}
                            </div>
                          ) : (
                            <div title="The pack size couldn't be converted to a price per 100 g, 100 mL or each, so this price isn't compared per unit.">
                              <span className="chip chip-amber" style={{ fontSize: "0.65rem" }}>no unit price</span>
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
