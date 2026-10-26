import { useEffect, useState } from "react";
import { system } from "../api/endpoints";
import type { LlmStatus } from "../api/types";

/** Shows which LLM is driving the agents, and warns when it has fallen back to the offline mock. */
export default function ModelBadge() {
  const [status, setStatus] = useState<LlmStatus | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => system.llm().then((s) => alive && setStatus(s)).catch(() => {});
    load();
    const id = window.setInterval(load, 20000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (!status) return null;
  const offline = status.mode === "offline" || status.mode === "offline_unconfigured";
  const degraded = status.mode === "degraded";
  const detail = status.config_error ?? status.last_error;
  const title = detail ? `${status.mode_label}. ${detail}` : `${status.mode_label}. ${status.calls} LLM calls this run.`;
  return (
    <span className={`chip ${offline ? "" : degraded ? "chip-amber" : "chip-produce"}`} title={title}>
      <span className="mono">{offline ? "Offline agent mode" : `${status.model}`}</span>
      {degraded && <span>· {status.fallbacks} fallback{status.fallbacks === 1 ? "" : "s"}</span>}
    </span>
  );
}
