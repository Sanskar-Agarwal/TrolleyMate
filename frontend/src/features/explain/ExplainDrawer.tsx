import { explain } from "../../api/endpoints";
import Drawer from "../../components/Drawer";
import Skeleton from "../../components/Skeleton";
import { useLoad } from "../../lib/useLoad";
import { useShop } from "../shop/ShopContext";

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
        <div className="stack">
          <p style={{ fontSize: "var(--step-1)" }}>{data.text}</p>
          {!data.available && <div className="notice notice-amber">No recorded reasoning exists for this, so none is shown.</div>}
          {data.facts && (
            <details>
              <summary className="small muted" style={{ cursor: "pointer" }}>
                Recorded facts this explanation is based on
              </summary>
              <pre className="mono small" style={{ whiteSpace: "pre-wrap", background: "var(--surface-2)", padding: 12, borderRadius: 6 }}>
                {JSON.stringify(data.facts, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </Drawer>
  );
}
