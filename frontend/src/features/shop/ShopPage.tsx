import AgentTrace from "../../components/AgentTrace";
import BasketWorkspace from "../basket/BasketWorkspace";
import GoalPicker from "../basket/GoalPicker";
import ChatPanel from "../intake/ChatPanel";
import ConstraintCard from "../intake/ConstraintCard";
import StartPanel from "../intake/StartPanel";
import NegotiationPanel from "../negotiation/NegotiationPanel";
import { ShopProvider, useShop } from "./ShopContext";
import "./ShopPage.css";

const STAGES = ["Describe", "Confirm", "Basket", "Meals"] as const;

function Workspace() {
  const { state, trace, busy, error, clearError, negotiation, newSession } = useShop();
  if (!state) {
    return <div className="shop-loading muted">{error ?? "Opening your shop…"}</div>;
  }

  const draft = state.intake?.status === "draft";
  let stage = 0;
  if (draft) stage = 1;
  else if (state.constraints) stage = state.meal_plan ? 3 : 2;

  return (
    <div className="shop">
      <aside className="shop-chat">
        <ChatPanel />
      </aside>

      <section className="shop-main" aria-busy={!!busy}>
        <div className="spread">
          <ol className="stage-rail" aria-label="Progress">
            {STAGES.map((label, i) => (
              <li key={label} className={i < stage ? "done" : i === stage ? "current" : ""} aria-current={i === stage ? "step" : undefined}>
                <span className="mono">{i + 1}</span> {label}
              </li>
            ))}
          </ol>
          {(state.constraints || state.basket) && (
            <button className="btn btn-ghost btn-sm" onClick={newSession} disabled={!!busy}>
              Start a new shop
            </button>
          )}
        </div>

        {error && (
          <div className="notice notice-beet" role="alert">
            <span style={{ flex: 1 }}>{error}</span>
            <button className="btn btn-ghost btn-sm" onClick={clearError}>
              Dismiss
            </button>
          </div>
        )}

        {stage === 0 && <StartPanel />}
        {draft && <ConstraintCard />}
        {!draft && negotiation && <NegotiationPanel />}
        {!draft && state.constraints && !state.basket && !negotiation && <GoalPicker />}
        {!draft && state.basket && <BasketWorkspace />}
      </section>

      <aside className="shop-trace">
        <AgentTrace steps={trace} busy={busy} />
      </aside>
    </div>
  );
}

export default function ShopPage() {
  return (
    <ShopProvider>
      <Workspace />
    </ShopProvider>
  );
}
