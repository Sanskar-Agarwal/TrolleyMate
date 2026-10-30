import { useState } from "react";
import { households } from "../../api/endpoints";
import type { Restriction } from "../../api/types";
import { useLoad } from "../../lib/useLoad";

export type PreferenceField = { kind: string; value: string };

export const PREFERENCE_KINDS = [
  { id: "dislike", label: "Dislike" },
  { id: "like", label: "Like" },
  { id: "brand", label: "Preferred brand" },
  { id: "avoid_brand", label: "Avoid brand" },
];
const SEVERITIES = ["severe", "moderate", "mild"];

/** Request corrections never alter the household's mandatory rules. */
export default function DietaryFields({ restrictions, preferences, disabled, onRestrictions, onPreferences }: {
  restrictions: Restriction[];
  preferences: PreferenceField[];
  disabled: boolean;
  onRestrictions: (value: Restriction[]) => void;
  onPreferences: (value: PreferenceField[]) => void;
}) {
  const vocab = useLoad(() => households.vocabulary(), "intake-restrictions");
  const [addition, setAddition] = useState("");
  const options = (vocab.data ?? []).filter((v) => !restrictions.some((r) => r.restriction === v.id));
  const changePreference = (index: number, patch: Partial<PreferenceField>) =>
    onPreferences(preferences.map((p, i) => i === index ? { ...p, ...patch } : p));

  return (
    <fieldset className="intake-dietary stack" disabled={disabled}>
      <legend className="eyebrow">Dietary rules and preferences</legend>
      <div className="stack" style={{ "--gap": "8px" } as React.CSSProperties}>
        <strong>Never in the basket</strong>
        {restrictions.length === 0 && <span className="small muted">No restrictions.</span>}
        {restrictions.map((r) => {
          const label = r.label ?? vocab.data?.find((v) => v.id === r.restriction)?.label ?? r.restriction;
          return (
            <div className="intake-edit-row" key={r.restriction}>
              <span className="chip chip-beet">{r.locked && <span aria-hidden="true">🔒 </span>}{label}</span>
              {r.locked ? (
                <span className="small muted">{r.severity} · Required by your household{r.members?.length ? ` (${r.members.join(", ")})` : ""}. Change this in your household profile.</span>
              ) : (
                <>
                  <select className="input" aria-label={`${label} severity`} value={r.severity}
                    onChange={(e) => onRestrictions(restrictions.map((item) => item.restriction === r.restriction ? { ...item, severity: e.target.value } : item))}>
                    {SEVERITIES.map((severity) => <option key={severity} value={severity}>{severity[0].toUpperCase() + severity.slice(1)}</option>)}
                  </select>
                  <button className="btn btn-sm btn-ghost" type="button" aria-label={`Remove ${label} restriction`}
                    onClick={() => onRestrictions(restrictions.filter((item) => item.restriction !== r.restriction))}>Remove</button>
                </>
              )}
            </div>
          );
        })}
        <div className="intake-edit-row">
          <select className="input" aria-label="Add dietary restriction" value={addition} onChange={(e) => setAddition(e.target.value)} disabled={disabled || !options.length}>
            <option value="">{vocab.loading ? "Loading dietary rules…" : "Choose a dietary rule"}</option>
            {options.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
          <button className="btn btn-sm" type="button" disabled={!options.some((v) => v.id === addition)} onClick={() => {
            const selected = options.find((v) => v.id === addition);
            if (!selected) return;
            onRestrictions([...restrictions, { restriction: selected.id, label: selected.label, severity: "severe" }]);
            setAddition("");
          }}>Add restriction</button>
        </div>
        {vocab.error && <p className="small" role="alert">Dietary choices could not be loaded. <button className="btn btn-sm" type="button" onClick={() => void vocab.reload()}>Retry dietary choices</button></p>}
      </div>
      <div className="stack" style={{ "--gap": "8px" } as React.CSSProperties}>
        <strong>Preferences for this shop</strong>
        <p className="small muted">You can change these for this request. Household allergies and dietary rules always take priority.</p>
        {preferences.length === 0 && <span className="small muted">No preferences.</span>}
        {preferences.map((p, index) => (
          <div className="intake-edit-row" key={index}>
            <select className="input" aria-label={`Preference ${index + 1} type`} value={p.kind}
              aria-invalid={!PREFERENCE_KINDS.some((kind) => kind.id === p.kind)}
              aria-describedby={!PREFERENCE_KINDS.some((kind) => kind.id === p.kind) ? "preference-validation" : undefined}
              onChange={(e) => changePreference(index, { kind: e.target.value })}>
              {!PREFERENCE_KINDS.some((kind) => kind.id === p.kind) && <option value={p.kind}>Choose a preference type</option>}
              {PREFERENCE_KINDS.map((kind) => <option key={kind.id} value={kind.id}>{kind.label}</option>)}
            </select>
            <input className="input" aria-label={`Preference ${index + 1} value`} value={p.value} placeholder="Food or brand"
              aria-invalid={!p.value.trim()} aria-describedby={!p.value.trim() ? "preference-validation" : undefined}
              onChange={(e) => changePreference(index, { value: e.target.value })} />
            <button className="btn btn-sm btn-ghost" type="button" aria-label={`Remove preference ${index + 1}`}
              onClick={() => onPreferences(preferences.filter((_, i) => i !== index))}>Remove</button>
          </div>
        ))}
        {preferences.some((p) => !p.value.trim() || !PREFERENCE_KINDS.some((kind) => kind.id === p.kind)) && <p id="preference-validation" className="small" role="status">Choose a type and enter a food or brand for each preference, or remove the preference.</p>}
        <div><button className="btn btn-sm" type="button" onClick={() => onPreferences([...preferences, { kind: "dislike", value: "" }])}>Add preference</button></div>
      </div>
    </fieldset>
  );
}
