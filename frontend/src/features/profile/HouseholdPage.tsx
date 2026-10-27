import { useState } from "react";
import { households, type MemberInput } from "../../api/endpoints";
import type { Household, HouseholdMember } from "../../api/types";
import { useToast } from "../../components/Toast";
import { useLoad } from "../../lib/useLoad";
import PreferencesPanel from "../preferences/PreferencesPanel";
import "./profile.css";

const SEVERITIES = [
  { id: "severe", label: "Severe allergy" },
  { id: "moderate", label: "Intolerance / diet" },
  { id: "mild", label: "Mild" },
];

function MemberEditor({
  initial,
  vocab,
  onSave,
  onCancel,
}: {
  initial: MemberInput;
  vocab: { id: string; label: string; kind: string }[];
  onSave: (m: MemberInput) => Promise<void>;
  onCancel: () => void;
}) {
  const [m, setM] = useState<MemberInput>(initial);
  const [add, setAdd] = useState(vocab[0]?.id ?? "");
  const [sev, setSev] = useState("severe");
  return (
    <form
      className="card-flat stack"
      onSubmit={(e) => {
        e.preventDefault();
        void onSave(m);
      }}
    >
      <div className="row">
        <label className="field" style={{ flex: 2, minWidth: 160 }}>
          <span>Name</span>
          <input className="input" value={m.name} onChange={(e) => setM({ ...m, name: e.target.value })} required />
        </label>
        <label className="field" style={{ flex: 1, minWidth: 120 }}>
          <span>Age group</span>
          <select className="input" value={m.age_group} onChange={(e) => setM({ ...m, age_group: e.target.value })}>
            {["adult", "teen", "child", "senior"].map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
        {m.restrictions.map((r) => (
          <button
            type="button"
            key={r.restriction}
            className="chip chip-beet"
            onClick={() => setM({ ...m, restrictions: m.restrictions.filter((x) => x.restriction !== r.restriction) })}
            aria-label={`Remove ${r.restriction}`}
          >
            {vocab.find((v) => v.id === r.restriction)?.label ?? r.restriction} · {r.severity} ✕
          </button>
        ))}
        {m.restrictions.length === 0 && <span className="small muted">No restrictions.</span>}
      </div>
      <div className="row">
        <select className="input" style={{ width: "auto" }} value={add} onChange={(e) => setAdd(e.target.value)} aria-label="Restriction">
          {vocab.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label}
            </option>
          ))}
        </select>
        <select className="input" style={{ width: "auto" }} value={sev} onChange={(e) => setSev(e.target.value)} aria-label="Severity">
          {SEVERITIES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() =>
            !m.restrictions.some((r) => r.restriction === add) && setM({ ...m, restrictions: [...m.restrictions, { restriction: add, severity: sev }] })
          }
        >
          Add restriction
        </button>
      </div>
      <div className="row">
        <button className="btn btn-primary btn-sm">Save member</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** UC-10: household members and their dietary profiles. */
export default function HouseholdPage() {
  const household = useLoad(() => households.me(), "me");
  const vocab = useLoad(() => households.vocabulary(), "vocab");
  const [data, setData] = useState<Household | null>(null);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const h = data ?? household.data;

  // The editor stays open on failure so nothing typed is lost; the cards keep showing the
  // last saved profile, which is what the server still has.
  async function save(fn: () => Promise<{ household: Household }>) {
    setError(null);
    try {
      const r = await fn();
      setData(r.household);
      setEditing(null);
      toast("Saved. This applies from your next shop.");
    } catch (e) {
      const message = (e as Error).message;
      setError(message.includes("hasn't changed") ? message : `${message} Your saved profile hasn't changed.`);
    }
  }

  if (!h || !vocab.data) return <div className="page muted">{household.error ?? "Loading household…"}</div>;
  const toInput = (m: HouseholdMember): MemberInput => ({
    name: m.name,
    age_group: m.age_group,
    restrictions: m.restrictions.map((r) => ({ restriction: r.restriction, severity: r.severity })),
  });

  return (
    <div className="page">
      <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
        <span className="eyebrow">Household profile</span>
        <h1>{h.name}</h1>
        <p className="muted">
          Everyone's allergies and dietary rules are combined for every shop. Mandatory restrictions always beat preferences.
        </p>
      </div>
      {error && <div className="notice notice-beet" role="alert">{error}</div>}

      <div className="profile-grid">
        <section className="stack">
          <div className="spread">
            <h3>Members</h3>
            <button className="btn btn-sm" onClick={() => setEditing("new")}>
              Add member
            </button>
          </div>
          {editing === "new" && (
            <MemberEditor
              initial={{ name: "", age_group: "adult", restrictions: [] }}
              vocab={vocab.data}
              onSave={(m) => save(() => households.addMember(m))}
              onCancel={() => setEditing(null)}
            />
          )}
          {h.members.map((m) =>
            editing === m.id ? (
              <MemberEditor
                key={m.id}
                initial={toInput(m)}
                vocab={vocab.data!}
                onSave={(mi) => save(() => households.updateMember(m.id, mi))}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <div key={m.id} className="card-flat spread member">
                <div className="stack" style={{ "--gap": "6px" } as React.CSSProperties}>
                  <strong>
                    {m.name} <span className="small muted">· {m.age_group}</span>
                  </strong>
                  <div className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
                    {m.restrictions.length === 0 && <span className="small muted">No restrictions</span>}
                    {m.restrictions.map((r) => (
                      <span key={r.id} className="chip chip-beet">
                        {vocab.data!.find((v) => v.id === r.restriction)?.label ?? r.restriction} · {r.severity}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="row">
                  <button className="btn btn-sm" onClick={() => setEditing(m.id)}>
                    Edit
                  </button>
                  <button className="btn btn-sm btn-danger" onClick={() => save(() => households.removeMember(m.id))} disabled={h.members.length <= 1}>
                    Remove
                  </button>
                </div>
              </div>
            ),
          )}
        </section>

        <aside className="stack">
          <div className="card-flat stack">
            <span className="eyebrow">Applied to every shop</span>
            {h.mandatory_restrictions.length === 0 && <span className="small muted">No saved restrictions.</span>}
            {h.mandatory_restrictions.map((r) => (
              <div key={r.restriction} className="spread small">
                <span className="chip chip-beet">{vocab.data!.find((v) => v.id === r.restriction)?.label ?? r.restriction}</span>
                <span className="muted">{r.severity} · {r.members?.join(", ")}</span>
              </div>
            ))}
          </div>
          <PreferencesPanel household={h} onChange={setData} />
        </aside>
      </div>
    </div>
  );
}
