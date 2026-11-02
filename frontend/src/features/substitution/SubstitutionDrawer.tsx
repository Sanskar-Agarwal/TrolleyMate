import { useEffect, useRef, useState } from "react";
import { substitutions } from "../../api/endpoints";
import type { BasketItem, Substitution } from "../../api/types";
import Drawer from "../../components/Drawer";
import ShelfTag from "../../components/ShelfTag";
import Skeleton from "../../components/Skeleton";
import { money } from "../../lib/format";
import { useShop } from "../shop/ShopContext";
import "./substitution.css";

const FLAG_LABEL: Record<string, string> = {
  out_of_stock: "Out of stock",
  over_budget: "Basket is over budget",
  failed_review: "Failed dietary review",
};

/** UC-04: propose a compliant swap and state its trade-off; the shopper accepts or declines.
 * A system-flagged item (out of stock, over budget, failed review) is proposed for that reason. */
export default function SubstitutionDrawer({ item, onClose }: { item: BasketItem; onClose: () => void }) {
  const { state, run, setBasket, busy } = useShop();
  const basketId = state!.basket!.id;
  const [sub, setSub] = useState<Substitution | null>(null);
  const asked = useRef(false);
  const reason: string = item.flags?.[0] ?? "user_requested";

  useEffect(() => {
    if (asked.current) return; // StrictMode runs effects twice in dev; only propose once
    asked.current = true;
    run("Finding a safe substitute", () => substitutions.propose(basketId, item.id, reason), { refresh: false }).then((r) => {
      if (r) {
        setSub(r.substitution);
        setBasket(r.basket);
      }
    });
  }, [basketId, item.id, reason, run, setBasket]);

  async function decide(accept: boolean) {
    if (!sub) return;
    const r = await run(accept ? "Swapping it in" : "Keeping the original", () => (accept ? substitutions.accept(sub.id) : substitutions.reject(sub.id)), {
      toast: (r) =>
        !accept
          ? ["Kept the original. We won't suggest that swap again.", "info"]
          : r.substitution.status === "accepted"
            ? [`Swapped in ${sub.replacement?.name}`]
            : [r.substitution.trade_off, "info"],
    });
    if (r) {
      setBasket(r.basket);
      onClose();
    }
  }

  const saving = sub?.facts.saving ?? 0;
  return (
    <Drawer title={`Substitute for ${item.product.name}`} eyebrow="AI Personal Shopper" onClose={onClose}>
      {reason !== "user_requested" && <div className="notice notice-amber">{FLAG_LABEL[reason]}</div>}
      {!sub && <Skeleton rows={3} height={22} label="Checking alternatives against your household's dietary rules" />}

      {sub?.status === "discarded" && (
        <div className="stack">
          <div className="notice notice-amber">{sub.trade_off}</div>
          <button className="btn" onClick={onClose}>{reason === "out_of_stock" || reason === "failed_review" ? "Close" : `Keep ${item.product.name}`}</button>
        </div>
      )}

      {sub?.status === "pending" && sub.replacement && (
        <div className="stack" style={{ "--gap": "16px" } as React.CSSProperties}>
          <div className="swap">
            <div className="stack" style={{ "--gap": "6px" } as React.CSSProperties}>
              <span className="eyebrow">Now</span>
              <strong>{sub.original.name}</strong>
              <ShelfTag price={item.pack_price} unit={item.unit_price_label} muted />
            </div>
            <span className="swap-arrow" aria-hidden="true">→</span>
            <div className="stack" style={{ "--gap": "6px" } as React.CSSProperties}>
              <span className="eyebrow">Suggested</span>
              <strong>{sub.replacement.name}</strong>
              <ShelfTag price={sub.replacement_price} unit={sub.facts.unit_price ? `${money(sub.facts.unit_price)} / ${sub.facts.unit_basis === "each" ? "each" : sub.facts.unit_basis?.replace("100", "100 ")}` : null} />
              <span className="small muted">{sub.facts.retailer}</span>
            </div>
          </div>
          <div className={`notice ${saving >= 0 ? "notice-produce" : "notice-amber"}`}>
            <span><strong>Trade-off:</strong> {sub.trade_off}</span>
          </div>
          <p className="small muted">Already checked against every allergy and dietary rule in your household.</p>
          <div className="row">
            <button className="btn btn-primary" onClick={() => decide(true)} disabled={!!busy}>
              Swap it in
            </button>
            <button className="btn" onClick={() => decide(false)} disabled={!!busy}>
              Keep the original
            </button>
          </div>
        </div>
      )}
    </Drawer>
  );
}
