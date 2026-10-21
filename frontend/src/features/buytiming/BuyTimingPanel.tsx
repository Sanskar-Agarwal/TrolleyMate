import { timing } from "../../api/endpoints";
import Skeleton from "../../components/Skeleton";
import { money } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";
import { useShop } from "../shop/ShopContext";

/** 1.2.6: buy-timing advice from price history. Advice only; it never changes the basket. */
export default function BuyTimingPanel() {
  const { state, addTrace } = useShop();
  const basketId = state!.basket!.id;
  const { data, error } = useLoad(async () => {
    const r = await timing.advice(basketId);
    addTrace(r.trace);
    return r;
  }, basketId);

  if (error) return <div className="notice notice-beet">{error}</div>;
  if (!data) return <Skeleton rows={4} height={40} label="Reading eight weeks of price history" />;

  const { advice, history_note } = data;
  const waits = advice.filter((a) => a.action === "wait");
  const rest = advice.filter((a) => a.action !== "wait");
  const total = waits.reduce((s, a) => s + (a.expected_saving ?? 0), 0);

  return (
    <div className="stack" style={{ maxWidth: 820 }}>
      <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
        <span className="eyebrow">AI Market Analyst · buy timing</span>
        <h2>{waits.length ? `Wait on ${waits.length} item${waits.length === 1 ? "" : "s"} to save about ${money(total)}` : "Now is a good time to buy"}</h2>
        <p className="muted small">
          Based on recurring discounts at the store each item comes from. Daily staples and perishables that wouldn't keep are left out.
          Advice only: your basket doesn't change.
        </p>
      </div>
      {history_note && (
        <div className="notice notice-amber">
          <span>
            <strong>Demo data.</strong> {history_note} These patterns are illustrations, not forecasts.
          </span>
        </div>
      )}
      {waits.map((a) => (
        <div key={a.item_id} className="card-flat spread">
          <div className="stack" style={{ "--gap": "2px" } as React.CSSProperties}>
            <strong>{a.product}</strong>
            <span className="small muted">{a.reason}</span>
          </div>
          <div className="stack" style={{ "--gap": "2px", textAlign: "right" } as React.CSSProperties}>
            <span className="chip chip-produce">
              Wait {a.wait_days}d · {a.pattern_day}
              {a.wait_until ? ` (${a.wait_until})` : ""}
            </span>
            {a.history?.demo && <span className="chip">Demo history</span>}
            <span className="mono small">save ~{money(a.expected_saving)}</span>
          </div>
        </div>
      ))}
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th>Item</th>
              <th>Advice</th>
            </tr>
          </thead>
          <tbody>
            {rest.map((a) => (
              <tr key={a.item_id}>
                <td>{a.product}</td>
                <td className="muted">{a.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
