import type { Nutrition } from "../../api/types";
import { NUTRIENT_LABEL, nutrientValue } from "../../lib/format";
import "./compliance.css";

/** Nutritional adequacy (1.2.11): what the basket provides against what the meals need. */
export default function NutritionPanel({ nutrition }: { nutrition: Nutrition }) {
  const keys = Object.keys(nutrition.required);
  return (
    <div className="card-flat stack nutrition">
      <div className="spread">
        <span className="eyebrow">Nutrition cover</span>
        <span className={`chip ${nutrition.adequate ? "chip-produce" : "chip-amber"}`}>{nutrition.adequate ? "Adequate" : "Gaps found"}</span>
      </div>
      {keys.map((k) => {
        const need = nutrition.required[k];
        const have = nutrition.provided[k] ?? 0;
        const ratio = need > 0 ? Math.min(have / need, 1.5) : 1;
        return (
          <div key={k} className="nutrient">
            <div className="spread small">
              <span>{NUTRIENT_LABEL[k] ?? k}</span>
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
      {nutrition.suggestions.map((s) => (
        <p key={s} className="small muted">
          {s}
        </p>
      ))}
    </div>
  );
}
