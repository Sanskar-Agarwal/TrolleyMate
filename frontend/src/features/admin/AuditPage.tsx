import { useState } from "react";
import { audit } from "../../api/endpoints";
import type { AuditEntry } from "../../api/types";
import { AGENTS } from "../../components/AgentTrace";
import Drawer from "../../components/Drawer";
import { dateTime, sentence } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";
import "../profile/profile.css";
import "./admin.css";

const AGENT_NAMES = ["AI Personal Shopper", "AI Market Analyst", "AI Nutrition & Compliance", "AI Technical Manager"];
const KEY_BY_NAME: Record<string, string> = {
  "AI Personal Shopper": "personal_shopper",
  "AI Market Analyst": "market_analyst",
  "AI Nutrition & Compliance": "nutrition_compliance",
  "AI Technical Manager": "technical_manager",
};
const colour = (agent: string) => AGENTS[KEY_BY_NAME[agent] ?? "human_reviewer"]?.colour ?? "var(--muted)";

/** UC-07: the founder's view of every agent decision, with raw prompts and responses. */
export default function AuditPage() {
  const [agent, setAgent] = useState("");
  const [open, setOpen] = useState<AuditEntry | null>(null);
  const stats = useLoad(() => audit.stats(), "stats");
  const log = useLoad(() => audit.list({ agent: agent || undefined, limit: 200 }), agent);
  const s = stats.data;

  return (
    <div className="page" style={{ maxWidth: 1240 }}>
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">AI Technical Manager · governance</span>
          <h1>Agent audit log</h1>
        </div>
        <button className="btn btn-sm" onClick={() => { void log.reload(); void stats.reload(); }}>
          Refresh
        </button>
      </div>

      {s && (
        <div className="stat-strip">
          {AGENT_NAMES.map((name) => (
            <button key={name} className={`stat${agent === name ? " on" : ""}`} onClick={() => setAgent(agent === name ? "" : name)} style={{ borderTopColor: colour(name) }}>
              <span className="stat-n mono">{s.per_agent[name] ?? 0}</span>
              <span className="small">{name.replace("AI ", "")}</span>
            </button>
          ))}
          <div className="stat" style={{ borderTopColor: "var(--amber)" }}>
            <span className="stat-n mono">{s.open_cases}</span>
            <span className="small">Open human-review cases</span>
          </div>
          <div className="stat" style={{ borderTopColor: "var(--sky)" }}>
            <span className="stat-n mono">{s.llm.calls}</span>
            <span className="small">
              LLM calls · {s.llm.provider}:{s.llm.model}
              {s.llm.fallbacks > 0 ? ` · ${s.llm.fallbacks} fell back` : ""}
            </span>
          </div>
        </div>
      )}
      {s && (
        <p className="small muted">
          Policy: compliance confidence threshold {String(s.policy.safety_threshold)} · corrections before form {String(s.policy.max_corrections)} · price max age{" "}
          {String(s.policy.price_max_age_hours)} h · review SLA {String(s.policy.review_sla_minutes)} min · mandatory restrictions relaxable: no
        </p>
      )}

      {log.error && <div className="notice notice-beet">{log.error}</div>}
      <div className="table-scroll card" style={{ padding: 0 }}>
        <table className="data">
          <thead>
            <tr>
              <th>When</th>
              <th>Agent</th>
              <th>Action</th>
              <th>Decision</th>
              <th>Conf.</th>
              <th>Model</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(log.data ?? []).map((r) => (
              <tr key={r.id}>
                <td className="mono nowrap">{dateTime(r.timestamp)}</td>
                <td>
                  <span className="agent-dot" style={{ background: colour(r.agent) }} /> {r.agent.replace("AI ", "")}
                </td>
                <td className="mono">{sentence(r.action)}</td>
                <td>{r.decision}</td>
                <td className="mono">{r.confidence != null ? `${Math.round(r.confidence * 100)}%` : "N/A"}</td>
                <td className="mono small muted">{r.model_version}</td>
                <td>
                  <button className="btn btn-ghost btn-sm" onClick={() => setOpen(r)}>
                    Trace
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {log.data?.length === 0 && <div className="empty" style={{ margin: 16 }}>No decisions recorded yet. Build a basket as a shopper to see the agents at work.</div>}
      </div>

      {open && (
        <Drawer title={sentence(open.action)} eyebrow={`${open.agent} · #${open.id}`} onClose={() => setOpen(null)}>
          <div className="stack">
            <p>{open.decision}</p>
            {open.rationale && <p className="small muted">{open.rationale}</p>}
            <p className="small mono muted">
              {open.model_version} · session {open.session_id ?? "N/A"} · basket {open.basket_id ?? "N/A"}
            </p>
            <pre className="mono small trace-json">{JSON.stringify(open.payload ?? {}, null, 2)}</pre>
          </div>
        </Drawer>
      )}
    </div>
  );
}
