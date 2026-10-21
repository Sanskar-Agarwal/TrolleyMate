import { useState } from "react";
import { compliance } from "../../api/endpoints";
import type { Nutrition, NutritionRepair } from "../../api/types";
import { NUTRIENT_LABEL, dateTime, money, nutrientValue } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";
import { useShop } from "../shop/ShopContext";
import "./compliance.css";

const label = (k: string) => NUTRIENT_LABEL[k] ?? k;

/**
 * Nutritional adequacy (1.2.11): what the basket provides against what the meals need, candidate
 * repairs for each open gap, and the shopper's explicit acceptance of a gap they're happy with.
 */
export default function NutritionPanel({ nutrition }: { nutrition: Nutrition }) {
  const { state, run, setBasket, busy } = useShop();
  const basketId = state?.basket?.id;
  const keys = Object.keys(nutrition.required);
  const accepted = new Set((nutrition.coverage ?? []).filter((c) => c.accepted).map((c) => c.nutrient));
  const open = nutrition.gaps.filter((g) => !accepted.has(g.nutrient));
  const repairs = useLoad<NutritionRepair[]>(
    () => (basketId && open.length ? compliance.nutrition(basketId).then((r) => r.repairs) : Promise.resolve([])),
    `${basketId}:${open.map((g) => `${g.nutrient}=${g.short_by}`).join(",")}`,
  );
  const [accepting, setAccepting] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const acceptGap = async (nutrient: string) => {
    if (!basketId) return;
    const r = await run("Recording your decision", () => compliance.acceptGap(basketId, [nutrient], note.trim()), {
      toast: () => [`${label(nutrient)} gap accepted.`],
    });
    if (r) {
      setBasket(r.basket);
      setAccepting(null);
      setNote("");
    }
  };

  const status = !nutrition.adequate ? "Gaps found" : accepted.size ? "Adequate with exception" : "Adequate";
  return (
    <div className="card-flat stack nutrition">
      <div className="spread">
        <span className="eyebrow">Nutrition cover</span>
        <span className={`chip ${nutrition.adequate ? "chip-produce" : "chip-amber"}`}>{status}</span>
      </div>
      {keys.map((k) => {
        const need = nutrition.required[k];
        const have = nutrition.provided[k] ?? 0;
        const ratio = need > 0 ? Math.min(have / need, 1.5) : 1;
        return (
          <div key={k} className="nutrient">
            <div className="spread small">
              <span>
                {label(k)} {accepted.has(k) && <span className="chip chip-tag">accepted</span>}
              </span>
              <span className="mono muted">
                {nutrientValue(k, have)} / {nutrientValue(k, need)}
              </span>
            </div>
            <div className="bar">
              <span style={{ width: `${(ratio / 1.5) * 100}%` }} className={have >= need ? "ok" : "short"} />
              <i style={{ left: `${(1 / 1.5) * 100}%` }} aria-hidden="true" />
            </div>
          </div>
        );
      })}

      {open.map((g) => (
        <div key={g.nutrient} className="stack gap-card" style={{ "--gap": "6px" } as React.CSSProperties}>
          <p className="small">
            <strong>{label(g.nutrient)}</strong> is short by {nutrientValue(g.nutrient, g.short_by)}.
          </p>
          {repairs.data
            ?.filter((r) => r.nutrient === g.nutrient)
            .map((r) => (
              <p key={r.product_id} className="small repair">
                Add {r.quantity} × {r.product}{" "}
                <span className="mono muted">
                  {money(r.cost)} at {r.retailer}
                </span>
                {!r.closes_gap && <span className="muted"> (closes part of it)</span>}{" "}
                {!r.within_budget && <span className="chip chip-amber">over budget</span>}
              </p>
            ))}
          {accepting === g.nutrient ? (
            <div className="stack accept-gap" style={{ "--gap": "6px" } as React.CSSProperties}>
              <label className="field small">
                <span>Why is this gap OK? (optional)</span>
                <input className="input" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
              </label>
              <p className="small muted">Your allergies and dietary rules still apply.</p>
              <div className="row">
                <button className="btn btn-sm btn-primary" disabled={!!busy} onClick={() => acceptGap(g.nutrient)}>
                  Accept the {label(g.nutrient).toLowerCase()} gap
                </button>
                <button className="btn btn-sm btn-ghost" onClick={() => setAccepting(null)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => {
                setAccepting(g.nutrient);
                setNote("");
              }}
            >
              I'm OK with this gap…
            </button>
          )}
        </div>
      ))}

      {open.length > 0 &&
        !repairs.data?.length &&
        nutrition.suggestions.map((s) => (
          <p key={s} className="small muted">
            {s}
          </p>
        ))}
      {nutrition.exceptions
        ?.filter((e) => accepted.has(e.nutrient))
        .map((e) => (
          <p key={e.nutrient} className="small muted">
            You accepted {label(e.nutrient).toLowerCase()} short by {nutrientValue(e.nutrient, e.short_by)}
            {e.note && `: "${e.note}"`} ({e.accepted_by}, {dateTime(e.accepted_at)}).
          </p>
        ))}
    </div>
  );
}
