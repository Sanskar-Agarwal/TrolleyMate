import { useState } from "react";
import { preferences } from "../../api/endpoints";
import type { Household } from "../../api/types";

const KINDS = [
  { id: "dislike", label: "Dislikes" },
  { id: "like", label: "Likes" },
  { id: "brand", label: "Preferred brand" },
  { id: "avoid_brand", label: "Avoid brand" },
];

/** 1.2.12: taste & preference memory. Soft: never overrides allergies or diets. */
export default function PreferencesPanel({ household, onChange }: { household: Household; onChange: (h: Household) => void }) {
  const [kind, setKind] = useState("dislike");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<{ household: Household }>) {
    setError(null);
    try {
      onChange((await fn()).household);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="card-flat stack">
      <span className="eyebrow">Remembered preferences</span>
      <p className="small muted">Used on every basket, but always second to allergies and dietary rules.</p>
      <div className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
        {household.preferences.length === 0 && <span className="small muted">None yet.</span>}
        {household.preferences.map((p) => (
          <button key={p.id} className="chip" onClick={() => act(() => preferences.remove(p.id))} aria-label={`Forget ${p.kind} ${p.value}`}>
            {KINDS.find((k) => k.id === p.kind)?.label ?? p.kind}: {p.value} ✕
          </button>
        ))}
      </div>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) void act(() => preferences.add(kind, value.trim())).then(() => setValue(""));
        }}
      >
        <select className="input" style={{ width: "auto" }} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Preference type">
          {KINDS.map((k) => (
            <option key={k.id} value={k.id}>
              {k.label}
            </option>
          ))}
        </select>
        <input className="input" style={{ flex: 1, minWidth: 120 }} value={value} onChange={(e) => setValue(e.target.value)} placeholder="e.g. mushrooms" />
        <button className="btn btn-sm" disabled={!value.trim()}>
          Remember
        </button>
      </form>
      {error && <div className="notice notice-beet">{error}</div>}
    </div>
  );
}
