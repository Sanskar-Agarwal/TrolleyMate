import { useEffect, useState } from "react";
import type { ConstraintDraft } from "../../api/types";
import { useShop } from "../shop/ShopContext";

type Fields = { budget: string; household_size: string; meals_per_day: string; days: string; protein: string };

function toFields(d: ConstraintDraft): Fields {
  const protein = d.nutritional_targets?.find((t) => t.nutrient === "protein_g")?.minimum_per_day;
  return {
    budget: d.budget?.toString() ?? "",
    household_size: d.household_size?.toString() ?? "",
    meals_per_day: d.meals_per_day?.toString() ?? "",
    days: d.days?.toString() ?? "",
    protein: protein?.toString() ?? "",
  };
}

function toPatch(f: Fields): Partial<ConstraintDraft> {
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const patch: Partial<ConstraintDraft> = {
    budget: num(f.budget),
    household_size: num(f.household_size),
    meals_per_day: num(f.meals_per_day),
    days: num(f.days),
  };
  if (f.protein.trim()) patch.nutritional_targets = [{ nutrient: "protein_g", minimum_per_day: Number(f.protein) }];
  return patch;
}

/** Stage 2 — review the interpreted constraints (UC-01 steps 3–5, extensions 2a and 4a). */
export default function ConstraintCard() {
  const { state, busy, correct, clarify, submitForm, confirm, cancel } = useShop();
  const intake = state!.intake!;
  const [fields, setFields] = useState<Fields>(toFields(intake.draft));
  const [answer, setAnswer] = useState("");
  const dirty = JSON.stringify(toPatch(fields)) !== JSON.stringify(toPatch(toFields(intake.draft)));

  useEffect(() => setFields(toFields(intake.draft)), [intake.draft]);

  const formMode = intake.mode === "form";
  const left = Math.max(0, intake.max_corrections - intake.correction_count);
  const missing = new Set([...intake.missing_fields, ...intake.questions.map((q) => q.field)]);
  const set = (k: keyof Fields) => (e: React.ChangeEvent<HTMLInputElement>) => setFields((f) => ({ ...f, [k]: e.target.value }));

  const field = (k: keyof Fields, label: string, suffix: string, attrs: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className={`docket-field${missing.has(k === "protein" ? "nutritional_targets" : k) ? " needs" : ""}`}>
      <span className="eyebrow">{label}</span>
      <span className="docket-input">
        {k === "budget" && <span className="mono">$</span>}
        <input className="mono" inputMode="decimal" value={fields[k]} onChange={set(k)} placeholder="?" {...attrs} />
        <span className="small muted">{suffix}</span>
      </span>
    </label>
  );

  return (
    <div className="card stack constraint-card">
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">Step 2 · Check what I understood</span>
          <h2>{formMode ? "Let's fill this in together" : "Here's your shop, as I read it"}</h2>
        </div>
        <span className={`chip ${formMode ? "chip-amber" : ""}`}>
          {formMode ? "Structured form" : left > 0 ? `${left} quick fix${left === 1 ? "" : "es"} before the form` : "Form next"}
        </span>
      </div>

      {intake.questions.length > 0 && (
        <form
          className="questions"
          onSubmit={(e) => {
            e.preventDefault();
            if (answer.trim()) void clarify(answer).then(() => setAnswer(""));
          }}
        >
          <span className="questions-badge" aria-hidden="true">?</span>
          <div className="stack" style={{ flex: 1, "--gap": "8px" } as React.CSSProperties}>
            <span className="eyebrow">Quick question first</span>
            {intake.questions.map((q) => (
              <strong key={q.field} className="question">
                {q.question}
              </strong>
            ))}
            <div className="row">
              <input
                className="input"
                style={{ flex: 1, minWidth: 180 }}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Type your answer"
                aria-label="Your answer"
                autoFocus
              />
              <button className="btn btn-sticker" disabled={!answer.trim() || !!busy}>
                Answer
              </button>
            </div>
          </div>
        </form>
      )}

      <blockquote className="raw-request">“{intake.raw_text}”</blockquote>

      <div className="docket-grid">
        {field("budget", "Budget", "AUD total", { "aria-label": "Budget in dollars" })}
        {field("household_size", "People", "in household")}
        {field("meals_per_day", "Meals", "per day")}
        {field("days", "Days", "to cover")}
        {field("protein", "Protein", "g / person / day (optional)")}
      </div>

      <div className="stack" style={{ "--gap": "8px" } as React.CSSProperties}>
        <span className="eyebrow">Never in the basket</span>
        <div className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
          {(intake.draft.restrictions ?? []).length === 0 && <span className="small muted">No restrictions.</span>}
          {(intake.draft.restrictions ?? []).map((r) => (
            <span key={r.restriction} className="chip chip-beet" title={r.locked ? `From your household profile${r.members ? ` (${r.members.join(", ")})` : ""} — can't be removed here` : "From this request"}>
              {r.locked && <span aria-hidden="true">🔒</span>}
              {r.label ?? r.restriction} · {r.severity}
            </span>
          ))}
        </div>
        {(intake.draft.preferences ?? []).length > 0 && (
          <p className="small muted">Preferences (soft): {intake.draft.preferences!.map((p) => p.replace(":", " ")).join(", ")}</p>
        )}
        {intake.assumptions.map((a) => (
          <p key={a} className="small muted">
            Assumed: {a}
          </p>
        ))}
      </div>

      <div className="spread">
        <button className="btn btn-ghost" onClick={cancel} disabled={!!busy}>
          Cancel request
        </button>
        <div className="row">
          {dirty && (
            <button className="btn" onClick={() => (formMode ? submitForm(toPatch(fields)) : correct(toPatch(fields)))} disabled={!!busy}>
              {formMode ? "Save form" : "Apply correction"}
            </button>
          )}
          <button className="btn btn-primary" onClick={confirm} disabled={!!busy || dirty || intake.missing_fields.length > 0}>
            Confirm constraints
          </button>
        </div>
      </div>
    </div>
  );
}
