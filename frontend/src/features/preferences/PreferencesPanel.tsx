import { useEffect, useState } from "react";
import { preferences } from "../../api/endpoints";
import type { Household, PreferenceKind, StoredPreference } from "../../api/types";
import "./preferences.css";

const KINDS: { id: PreferenceKind; label: string }[] = [
  { id: "dislike", label: "Dislike" },
  { id: "like", label: "Like" },
  { id: "brand", label: "Preferred brand" },
  { id: "avoid_brand", label: "Avoid brand" },
];

function names(p: StoredPreference): string {
  const more = p.match_count - p.matches.length;
  return p.matches.join(", ") + (more > 0 ? ` and ${more} more` : "");
}

/** What a preference does to the next shop, in the shopper's words. */
function effectNote(p: StoredPreference): string {
  switch (p.status) {
    case "applied":
      return p.effect === "avoid" ? `Left out of new baskets: ${names(p)}.` : `Picked in a close call: ${names(p)}.`;
    case "overridden":
      return "Never added: every match breaks a household restriction.";
    default:
      return "Nothing in the catalogue matches this yet.";
  }
}

function PreferenceForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: StoredPreference;
  submitLabel: string;
  onSubmit: (kind: PreferenceKind, value: string) => Promise<boolean>;
  onCancel?: () => void;
}) {
  const [kind, setKind] = useState<PreferenceKind>(initial?.kind ?? "dislike");
  const [value, setValue] = useState(initial?.value ?? "");
  return (
    <form
      className="row"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) void onSubmit(kind, value.trim()).then((ok) => ok && !initial && setValue(""));
      }}
    >
      <select className="input" style={{ width: "auto" }} value={kind} onChange={(e) => setKind(e.target.value as PreferenceKind)} aria-label="Preference type">
        {KINDS.map((k) => (
          <option key={k.id} value={k.id}>
            {k.label}
          </option>
        ))}
      </select>
      <input
        className="input"
        style={{ flex: 1, minWidth: 120 }}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="e.g. mushrooms"
        aria-label="Preference"
        maxLength={120}
      />
      <button className="btn btn-sm" disabled={!value.trim()}>
        {submitLabel}
      </button>
      {onCancel && (
        <button type="button" className="btn btn-sm btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      )}
    </form>
  );
}

/** 1.2.12: taste & preference memory. Soft: never overrides allergies or diets. */
export default function PreferencesPanel({ household, onChange }: { household: Household; onChange: (h: Household) => void }) {
  const [items, setItems] = useState<StoredPreference[] | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Statuses depend on the household's restrictions, so reload when a member's restrictions change.
  const rulesKey = `${household.id}|${household.mandatory_restrictions.map((r) => `${r.restriction}:${r.severity}`).join(",")}`;

  useEffect(() => {
    let live = true;
    setError(null);
    preferences
      .list()
      .then((list) => live && setItems(list))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [rulesKey]);

  async function act(fn: () => ReturnType<typeof preferences.remove>): Promise<boolean> {
    setError(null);
    try {
      const r = await fn();
      setItems(r.preferences);
      onChange(r.household);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  }

  return (
    <div className="card-flat stack">
      <span className="eyebrow">Remembered preferences</span>
      <p className="small muted">
        Dislikes and avoided brands are left out of every new shop. Likes and preferred brands win close calls, never over budget.
        Allergies and dietary rules always come first.
      </p>
      {items === null && !error && <span className="small muted">Loading preferences…</span>}
      {items?.length === 0 && <span className="small muted">None yet.</span>}
      {items && items.length > 0 && (
        <ul className="pref-list">
          {items.map((p) =>
            editing === p.id ? (
              <li key={p.id} className="pref">
                <PreferenceForm
                  initial={p}
                  submitLabel="Save"
                  onSubmit={async (kind, value) => {
                    const ok = await act(() => preferences.update(p.id, kind, value));
                    if (ok) setEditing(null);
                    return ok;
                  }}
                  onCancel={() => setEditing(null)}
                />
              </li>
            ) : (
              <li key={p.id} className="pref stack">
                <div className="spread">
                  <span className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
                    <span className={`chip ${p.effect === "avoid" ? "chip-beet" : "chip-produce"}`}>{p.label}</span>
                    <strong>{p.value}</strong>
                    {p.source === "learned" && <span className="chip chip-tag">learned</span>}
                  </span>
                  <span className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
                    <button className="btn btn-sm btn-ghost" onClick={() => setEditing(p.id)} aria-label={`Change ${p.label} ${p.value}`}>
                      Edit
                    </button>
                    <button className="btn btn-sm btn-danger" onClick={() => void act(() => preferences.remove(p.id))} aria-label={`Forget ${p.label} ${p.value}`}>
                      Forget
                    </button>
                  </span>
                </div>
                <span className="small muted">{effectNote(p)}</span>
                {p.blocked.map((b) => (
                  <span key={b.product} className="small pref-blocked">
                    Ruled out: {b.product} · {b.reason}
                  </span>
                ))}
                {p.hint && <div className="notice notice-amber">{p.hint}</div>}
              </li>
            ),
          )}
        </ul>
      )}
      <PreferenceForm submitLabel="Remember" onSubmit={(kind, value) => act(() => preferences.add(kind, value))} />
      {error && <div className="notice notice-beet">{error}</div>}
    </div>
  );
}
