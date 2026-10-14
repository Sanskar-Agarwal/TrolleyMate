import type { TraceStep } from "../api/types";
import { sentence, time } from "../lib/format";
import "./AgentTrace.css";

export const AGENTS: Record<string, { short: string; colour: string }> = {
  personal_shopper: { short: "Personal Shopper", colour: "var(--agent-shopper)" },
  market_analyst: { short: "Market Analyst", colour: "var(--agent-analyst)" },
  nutrition_compliance: { short: "Nutrition & Compliance", colour: "var(--agent-compliance)" },
  technical_manager: { short: "Technical Manager", colour: "var(--agent-manager)" },
  human_reviewer: { short: "Dietitian", colour: "var(--agent-human)" },
};

/** Live feed of what each agent decided during this session — perception, decision, action. */
export default function AgentTrace({ steps, busy }: { steps: TraceStep[]; busy?: string | null }) {
  const recent = [...steps].reverse().slice(0, 60);
  return (
    <section className="agent-trace" aria-label="Agent activity">
      <div className="spread">
        <span className="eyebrow">Agent activity</span>
        <span className="small muted mono">{steps.length} steps</span>
      </div>
      <ol>
        {busy && (
          <li className="trace-step working">
            <span className="dot" style={{ background: "var(--agent-shopper)" }} />
            <div>
              <div className="trace-head">
                <strong>Working</strong>
                <span className="spinner" />
              </div>
              <p>{busy}</p>
            </div>
          </li>
        )}
        {recent.length === 0 && !busy && (
          <li className="trace-empty small muted">
            Each agent's decisions appear here as it works: interpreting your request, pricing, safety checks, and the
            final choice.
          </li>
        )}
        {recent.map((s) => {
          const agent = AGENTS[s.agent] ?? { short: s.agent_name, colour: "var(--muted)" };
          return (
            <li key={s.id} className="trace-step">
              <span className="dot" style={{ background: agent.colour }} />
              <div>
                <div className="trace-head">
                  <strong style={{ color: agent.colour }}>{agent.short}</strong>
                  <span className="mono small muted">{time(s.at)}</span>
                </div>
                <p className="trace-action mono">{sentence(s.action)}</p>
                <p className="trace-decision">{s.decision}</p>
                <div className="row trace-meta" style={{ "--gap": "6px" } as React.CSSProperties}>
                  {s.llm && <span className={`chip ${s.fell_back ? "chip-amber" : "chip-sky"}`}>{s.fell_back ? "LLM → fallback" : `LLM · ${s.provider}`}</span>}
                  {!s.llm && <span className="chip">deterministic</span>}
                  {s.confidence != null && <span className="chip">conf {Math.round(s.confidence * 100)}%</span>}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
