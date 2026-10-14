import Drawer from "../../components/Drawer";
import { GOAL_LABEL, money } from "../../lib/format";
import { useShop } from "../shop/ShopContext";

/** The confirmed details behind the current basket (opened from the "Confirm" step). */
export default function ConstraintsDrawer({ onClose }: { onClose: () => void }) {
  const { state, focusChat, newSession, busy } = useShop();
  const c = state?.constraints;
  if (!c) return null;
  const p = c.payload;
  const protein = p.nutritional_targets?.find((t) => t.nutrient === "protein_g");

  return (
    <Drawer title="Your shop details" eyebrow={`Confirmed · version ${c.version}`} onClose={onClose}>
      <div className="stack" style={{ "--gap": "16px" } as React.CSSProperties}>
        <dl className="details-grid">
          <div>
            <dt className="eyebrow">Budget</dt>
            <dd>{money(p.budget)}</dd>
          </div>
          <div>
            <dt className="eyebrow">People</dt>
            <dd>{p.household_size}</dd>
          </div>
          <div>
            <dt className="eyebrow">Meals a day</dt>
            <dd>{p.meals_per_day}</dd>
          </div>
          <div>
            <dt className="eyebrow">Days</dt>
            <dd>{p.days}</dd>
          </div>
          {protein && (
            <div>
              <dt className="eyebrow">Protein</dt>
              <dd>{protein.minimum_per_day} g/day</dd>
            </div>
          )}
          {p.goal_hint && (
            <div>
              <dt className="eyebrow">Goal</dt>
              <dd>{GOAL_LABEL[p.goal_hint]}</dd>
            </div>
          )}
        </dl>
        <div className="stack" style={{ "--gap": "8px" } as React.CSSProperties}>
          <span className="eyebrow">Never in the basket</span>
          <div className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
            {(p.restrictions ?? []).length === 0 && <span className="small muted">No restrictions.</span>}
            {(p.restrictions ?? []).map((r) => (
              <span key={r.restriction} className="chip chip-beet">
                {r.label ?? r.restriction}
              </span>
            ))}
          </div>
        </div>
        {c.origin !== "intake" && (
          <p className="small muted">Last changed by {c.origin === "edit" ? "a basket edit" : "a budget trade-off"}.</p>
        )}
        <div className="notice">
          To change something, just tell your shopper — for example “make it $80” or “make it $10 cheaper”. For a
          different number of days or people, start a new shop.
        </div>
        <div className="row">
          <button
            className="btn btn-primary"
            onClick={() => {
              onClose();
              focusChat("Actually, ");
            }}
          >
            Change by chatting
          </button>
          <button className="btn" onClick={() => newSession().then(onClose)} disabled={!!busy}>
            Start a new shop
          </button>
        </div>
      </div>
    </Drawer>
  );
}
