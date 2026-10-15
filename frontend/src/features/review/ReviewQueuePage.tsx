import { useState } from "react";
import { escalations } from "../../api/endpoints";
import type { EscalationCase } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { dateTime, sentence } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";
import "../profile/profile.css";
import "./review.css";

const STATUS_CHIP: Record<string, string> = {
  open: "chip-amber",
  assigned: "chip-sky",
  under_review: "chip-sky",
  awaiting_information: "chip-amber",
  resolved: "chip-produce",
};

function CaseDetail({ c, onUpdate }: { c: EscalationCase; onUpdate: (c: EscalationCase) => void }) {
  const [question, setQuestion] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<{ case: EscalationCase }>) {
    setBusy(true);
    setError(null);
    try {
      onUpdate((await fn()).case);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const reviewing = c.status === "under_review" || c.status === "awaiting_information";
  return (
    <div className="card stack case-detail">
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">Case #{c.id} · {c.evidence.household}</span>
          <h2>{c.product}</h2>
        </div>
        <span className={`chip ${STATUS_CHIP[c.status] ?? ""}`}>{sentence(c.status)}</span>
      </div>

      <div className="notice notice-amber">
        <span>
          <strong>Why it was escalated:</strong> {c.reason}. Agent confidence {Math.round((c.evidence.confidence ?? 0) * 100)}% (threshold 95%).
        </span>
      </div>

      <div className="case-grid">
        <div className="stack" style={{ "--gap": "6px" } as React.CSSProperties}>
          <span className="eyebrow">Household must avoid</span>
          <div className="row" style={{ "--gap": "6px" } as React.CSSProperties}>
            {c.requirements.map((r) => (
              <span key={r.restriction} className="chip chip-beet">
                {r.label ?? r.restriction} · {r.severity}
              </span>
            ))}
          </div>
        </div>
        <div className="stack" style={{ "--gap": "6px" } as React.CSSProperties}>
          <span className="eyebrow">Product record</span>
          <p className="small">
            <strong>{c.product_detail.brand || "Unbranded"}</strong> · {c.product_detail.category}
          </p>
          <p className="small">
            Ingredients: {c.product_detail.ingredients.length ? c.product_detail.ingredients.join(", ") : <em className="muted">none on file</em>}
          </p>
          {c.product_detail.may_contain.length > 0 && <p className="small">May contain: {c.product_detail.may_contain.join(", ")}</p>}
          {!c.product_detail.data_complete && <span className="chip chip-amber">Incomplete retailer data</span>}
        </div>
      </div>

      {(c.evidence.findings ?? []).length > 0 && (
        <ul className="findings small">
          {c.evidence.findings!.map((f, i) => (
            <li key={i}>
              <span className="mono muted">{f.kind}</span> {f.ingredient && <strong>{f.ingredient}: </strong>}
              {f.detail}
            </li>
          ))}
        </ul>
      )}

      {c.thread.length > 0 && (
        <ol className="thread">
          {c.thread.map((t, i) => (
            <li key={i} className={t.from}>
              <span className="small muted">
                {t.author} · {dateTime(t.at)}
              </span>
              <p>{t.text}</p>
            </li>
          ))}
        </ol>
      )}

      {error && <div className="notice notice-beet">{error}</div>}

      {(c.status === "assigned" || c.status === "open") && (
        <button className="btn btn-primary" onClick={() => act(() => escalations.begin(c.id))} disabled={busy}>
          Start review
        </button>
      )}

      {reviewing && (
        <>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              if (question.trim()) void act(() => escalations.requestInfo(c.id, question)).then(() => setQuestion(""));
            }}
          >
            <input className="input" style={{ flex: 1, minWidth: 200 }} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the compliance agent for more information" />
            <button className="btn btn-sm" disabled={busy || !question.trim()}>
              Request info
            </button>
          </form>
          <label className="field">
            <span>Decision note (recorded in the audit log)</span>
            <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Manufacturer confirmed no dairy or nut ingredients." />
          </label>
          <div className="row">
            <button className="btn btn-primary" onClick={() => act(() => escalations.resolve(c.id, "passed", note))} disabled={busy}>
              Safe: release to basket
            </button>
            <button className="btn btn-danger" onClick={() => act(() => escalations.resolve(c.id, "failed", note))} disabled={busy}>
              Unsafe: exclude
            </button>
          </div>
        </>
      )}

      {c.status === "resolved" && (
        <div className={`notice ${c.resolution === "passed" ? "notice-produce" : "notice-beet"}`}>
          <span>
            <strong>{c.resolution === "passed" ? "Released to basket" : "Excluded from basket"}</strong> by {c.assigned_to} · {dateTime(c.resolved_at)}
            {c.resolution_note ? `: ${c.resolution_note}` : ""}
          </span>
        </div>
      )}
    </div>
  );
}

/** UC-06 ext: the human approval gate. Dietitians see their queue; the founder sees everything. */
export default function ReviewQueuePage() {
  const { user } = useAuth();
  const [filter, setFilter] = useState<"open" | "">("open");
  const [selected, setSelected] = useState<number | null>(null);
  const [overrides, setOverrides] = useState<Record<number, EscalationCase>>({});
  const queue = useLoad(() => escalations.queue(filter || undefined).then((r) => r.cases), filter);
  const cases = (queue.data ?? []).map((c) => overrides[c.id] ?? c);
  const current = cases.find((c) => c.id === selected) ?? cases[0];

  return (
    <div className="page">
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">{user?.role === "founder" ? "Founder exception queue" : `${user?.display_name} · ${user?.specialisation ?? "Dietitian"}`}</span>
          <h1>Items waiting for a human</h1>
          <p className="muted">The AI held these back because it couldn't confirm they're safe. Nothing reaches a basket without your decision.</p>
        </div>
        <div className="row">
          <select className="input" style={{ width: "auto" }} value={filter} onChange={(e) => setFilter(e.target.value as "open" | "")} aria-label="Filter">
            <option value="open">Open cases</option>
            <option value="">All cases</option>
          </select>
          <button className="btn btn-sm" onClick={() => queue.reload()}>
            Refresh
          </button>
        </div>
      </div>

      {queue.error && <div className="notice notice-beet">{queue.error}</div>}
      {queue.data && cases.length === 0 && <div className="empty">No cases waiting. When the compliance agent is unsure about an item, it lands here.</div>}

      {cases.length > 0 && (
        <div className="review-grid">
          <ul className="case-list">
            {cases.map((c) => (
              <li key={c.id}>
                <button className={`case-row${current?.id === c.id ? " on" : ""}`} onClick={() => setSelected(c.id)}>
                  <span className="spread">
                    <strong>{c.product}</strong>
                    <span className={`chip ${STATUS_CHIP[c.status] ?? ""}`}>{sentence(c.status)}</span>
                  </span>
                  <span className="small muted">
                    #{c.id} · {dateTime(c.created_at)} · {c.assigned_to ?? "unassigned"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {current && <CaseDetail key={current.id} c={current} onUpdate={(c) => setOverrides((o) => ({ ...o, [c.id]: c }))} />}
        </div>
      )}
    </div>
  );
}
