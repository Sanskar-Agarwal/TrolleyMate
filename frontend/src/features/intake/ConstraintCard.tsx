import { useEffect, useRef, useState } from "react";
import type { ConstraintDraft, Restriction } from "../../api/types";
import { useShop } from "../shop/ShopContext";
import DietaryFields, { PREFERENCE_KINDS, type PreferenceField } from "./DietaryFields";

const NUMBER_FIELDS = ["budget", "household_size", "meals_per_day", "days", "protein"] as const;
type NumberField = typeof NUMBER_FIELDS[number];
type Fields = Record<NumberField, string> & { restrictions: Restriction[]; preferences: PreferenceField[] };

function toFields(d: ConstraintDraft): Fields {
  const protein = d.nutritional_targets?.find((t) => t.nutrient === "protein_g")?.minimum_per_day;
  return {
    budget: d.budget?.toString() ?? "",
    household_size: d.household_size?.toString() ?? "",
    meals_per_day: d.meals_per_day?.toString() ?? "",
    days: d.days?.toString() ?? "",
    protein: protein?.toString() ?? "",
    restrictions: d.restrictions ?? [],
    preferences: (d.preferences ?? []).map((preference) => {
      const separator = preference.indexOf(":");
      return separator < 0 ? { kind: "", value: preference } : { kind: preference.slice(0, separator), value: preference.slice(separator + 1) };
    }),
  };
}

function toPatch(f: Fields, draft: ConstraintDraft): Partial<ConstraintDraft> {
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const patch: Partial<ConstraintDraft> = {
    budget: num(f.budget),
    household_size: num(f.household_size),
    meals_per_day: num(f.meals_per_day),
    days: num(f.days),
  };
  patch.nutritional_targets = (draft.nutritional_targets ?? []).filter((t) => t.nutrient !== "protein_g");
  if (f.protein.trim()) patch.nutritional_targets.push({ nutrient: "protein_g", minimum_per_day: Number(f.protein) });
  const locked = (draft.restrictions ?? []).filter((r) => r.locked);
  patch.restrictions = [...locked, ...f.restrictions.filter((r) => !locked.some((rule) => rule.restriction === r.restriction))]
    .map(({ restriction, severity }) => ({ restriction, severity }));
  patch.preferences = f.preferences.map((p) => `${p.kind ? `${p.kind}:` : ""}${p.value.trim()}`);
  return patch;
}

/** Stage 2: review the interpreted constraints (UC-01 steps 3–5, extensions 2a and 4a). */
export default function ConstraintCard() {
  const { state, busy, correct, clarify, submitForm, confirm, cancel } = useShop();
  const intake = state!.intake!;
  const serverFields = toFields(intake.draft);
  const [fields, setFields] = useState<Fields>(serverFields);
  const [answer, setAnswer] = useState("");
  const patch = toPatch(fields, intake.draft);
  const serverPatch = toPatch(serverFields, intake.draft);
  const correction = Object.fromEntries(Object.entries(patch).filter(([key, value]) =>
    JSON.stringify(value) !== JSON.stringify(serverPatch[key as keyof ConstraintDraft]))) as Partial<ConstraintDraft>;
  const dirty = Object.keys(correction).length > 0;

  // When the server draft changes (an answer, a correction), take only the fields whose
  // server value actually changed, so unsaved edits to other fields survive. A new
  // request starts the card over.
  const questionKey = JSON.stringify(intake.questions);
  const lastServer = useRef({ requestId: intake.request_id, fields: serverFields, questionKey });
  const serverKey = JSON.stringify(serverFields);
  useEffect(() => {
    const prev = lastServer.current;
    lastServer.current = { requestId: intake.request_id, fields: serverFields, questionKey };
    if (prev.requestId !== intake.request_id) {
      setFields(serverFields);
      setAnswer("");
      return;
    }
    if (prev.questionKey !== questionKey) setAnswer("");
    setFields((local) => {
      let next = { ...local };
      for (const k of Object.keys(serverFields) as (keyof Fields)[]) {
        if (JSON.stringify(serverFields[k]) !== JSON.stringify(prev.fields[k])) next = { ...next, [k]: serverFields[k] };
      }
      return next;
    });
    // serverKey captures every value serverFields is built from
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey, questionKey, intake.request_id]);

  const invalid = NUMBER_FIELDS.filter((key) => {
    if (!fields[key].trim()) return key !== "protein";
    const n = Number(fields[key]);
    return !Number.isFinite(n) || n <= 0 ||
      (key === "household_size" && (!Number.isInteger(n) || n > 20)) ||
      (key === "days" && (!Number.isInteger(n) || n > 31)) ||
      (key === "meals_per_day" && n > 5);
  });
  const invalidPreferences = fields.preferences.some((p) => !p.value.trim() || !PREFERENCE_KINDS.some((kind) => kind.id === p.kind));
  const formMode = intake.mode === "form";
  const needsFormSave = formMode && intake.stage === "awaiting_form";
  const left = Math.max(0, intake.max_corrections - intake.correction_count);
  const missing = new Set([...intake.missing_fields, ...intake.questions.map((q) => q.field)]);
  const set = (k: NumberField) => (e: React.ChangeEvent<HTMLInputElement>) => setFields((f) => ({ ...f, [k]: e.target.value }));

  const field = (k: NumberField, label: string, suffix: string, attrs: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className={`docket-field${missing.has(k === "protein" ? "nutritional_targets" : k) ? " needs" : ""}`}>
      <span className="eyebrow">{label}</span>
      <span className="docket-input">
        {k === "budget" && <span className="mono">$</span>}
        <input className="mono" disabled={!!busy} inputMode={k === "days" || k === "household_size" ? "numeric" : "decimal"} aria-invalid={invalid.includes(k)} aria-describedby={invalid.includes(k) ? "intake-validation" : undefined} value={fields[k]} onChange={set(k)} placeholder="?" {...attrs} />
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
            if (answer.trim() && !busy) void clarify(answer);
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
            {intake.questions.some((q) => q.field === "nutritional_targets") && !fields.protein.trim() && (
              <div><button className="btn btn-sm" type="button" disabled={!!busy} onClick={() => void clarify("No target")}>No extra protein target</button></div>
            )}
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

      <DietaryFields key={intake.request_id} restrictions={fields.restrictions} preferences={fields.preferences} disabled={!!busy}
        onRestrictions={(restrictions) => setFields((f) => ({ ...f, restrictions }))}
        onPreferences={(preferences) => setFields((f) => ({ ...f, preferences }))} />
      <div className="stack" style={{ "--gap": "8px" } as React.CSSProperties}>
        {intake.assumptions.map((a) => (
          <p key={a} className="small muted">
            Assumed: {a}
          </p>
        ))}
      </div>

      {invalid.length > 0 && <p id="intake-validation" className="notice notice-amber" role="status">Enter a positive budget, 1 to 20 people, up to 5 meals per day, and 1 to 31 days. People and days must be whole numbers. Protein is optional and must be positive if supplied.</p>}
      {dirty && <p className="small muted" role="status">You have unsaved changes. Apply them before confirming.</p>}

      <div className="spread">
        <button className="btn btn-ghost" onClick={cancel} disabled={!!busy}>
          Cancel request
        </button>
        <div className="row">
          {!formMode && <button className="btn" onClick={() => submitForm({})} disabled={!!busy}>Use a form instead</button>}
          {(dirty || needsFormSave) && (
            <button className="btn" onClick={() => (formMode ? submitForm(patch) : correct(correction))} disabled={!!busy || invalid.length > 0 || invalidPreferences}>
              {formMode ? "Save form" : "Apply correction"}
            </button>
          )}
          <button className="btn btn-primary" onClick={confirm} disabled={!!busy || dirty || needsFormSave || invalid.length > 0 || invalidPreferences || intake.missing_fields.length > 0 || intake.questions.length > 0}>
            Confirm constraints
          </button>
        </div>
      </div>
    </div>
  );
}
