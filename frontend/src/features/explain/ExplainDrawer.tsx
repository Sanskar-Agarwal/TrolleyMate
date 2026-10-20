import { explain } from "../../api/endpoints";
import type { ExplanationEvidence } from "../../api/types";
import Drawer from "../../components/Drawer";
import Skeleton from "../../components/Skeleton";
import { dateTime, money, sentence } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";
import { useShop } from "../shop/ShopContext";
import "./explain.css";

const MISSING_LABEL: Record<string, string> = {
  constraints: "Confirmed shop details",
  prices: "Price quotes",
  price: "Price quote",
  verdict: "Safety verdict",
  compliance: "Safety check",
  tools: "Optimiser results",
  audit_trail: "Agent decision log",
};

/** The records an explanation is built from, in plain language. */
function EvidenceList({ e }: { e: ExplanationEvidence }) {
  const rows: [string, string][] = [];
  if (e.constraints) {
    const c = e.constraints;
    rows.push(["Your shop details", `Version ${c.version}: ${money(c.budget)}, ${c.meals_per_day} meals/day for ${c.days} days, ${c.household_size} people`]);
  }
  if (e.prices) {
    const oldest = e.prices.map((p) => p.captured_at).sort()[0];
    const stores = new Set(e.prices.map((p) => p.retailer)).size;
    rows.push(["Prices", `${e.prices.length} quotes from ${stores} store${stores === 1 ? "" : "s"}, oldest ${dateTime(oldest)}`]);
  }
  if (e.price) rows.push(["Price", `${money(e.price.price)} at ${e.price.retailer}, recorded ${dateTime(e.price.captured_at)}`]);
  if (e.verdict) rows.push(["Safety check", `${sentence(e.verdict.status)}, ${Math.round(e.verdict.confidence * 100)}% confidence${e.verdict.source === "human" ? " (dietitian)" : ""}`]);
  if (e.compliance) rows.push(["Safety check", `${sentence(e.compliance.status)}, ${Math.round(e.compliance.confidence * 100)}% confidence`]);
  if (e.tools?.solver_ms != null) rows.push(["Optimiser", `Solved in ${e.tools.solver_ms} ms`]);
  if (e.audit_trail) rows.push(["Agent decisions", `${e.audit_trail.length} recorded for this basket`]);

  return (
    <div className="stack" style={{ "--gap": "10px" } as React.CSSProperties}>
      <span className="eyebrow">Based on these records</span>
      <dl className="evidence">
        {rows.map(([k, v]) => (
          <div key={k + v}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {e.missing.length > 0 && (
        <div className="notice notice-amber">
          <span>
            <strong>Not on record:</strong> {e.missing.map((m) => MISSING_LABEL[m] ?? m).join(", ")}. That part of the reasoning isn't
            shown rather than guessed.
          </span>
        </div>
      )}
      {e.unpriced_items && e.unpriced_items.length > 0 && (
        <p className="small muted">No recorded price for: {e.unpriced_items.join(", ")}.</p>
      )}
    </div>
  );
}

/** "Why this?": the explainability panel (UC-07). Text is generated only from recorded facts. */
export default function ExplainDrawer({ basketId, itemId, onClose }: { basketId: number; itemId?: number; onClose: () => void }) {
  const { addTrace } = useShop();
  const { data, error } = useLoad(async () => {
    const { trace, ...e } = await (itemId ? explain.item(basketId, itemId) : explain.basket(basketId));
    addTrace(trace);
    return e;
  }, `${basketId}:${itemId ?? "basket"}`);

  return (
    <Drawer title={itemId ? "Why this item?" : "Why this basket?"} eyebrow="Explained by the AI Technical Manager" onClose={onClose}>
      {!data && !error && <Skeleton rows={4} label="Writing up the reasoning" />}
      {error && <div className="notice notice-beet">{error}</div>}
      {data && (
        <div className="stack" style={{ "--gap": "18px" } as React.CSSProperties}>
          <p style={{ fontSize: "var(--step-1)" }}>{data.text}</p>
          {!data.available && <div className="notice notice-amber">No recorded reasoning exists for this, so none is shown.</div>}
          {data.evidence && <EvidenceList e={data.evidence} />}
        </div>
      )}
    </Drawer>
  );
}
