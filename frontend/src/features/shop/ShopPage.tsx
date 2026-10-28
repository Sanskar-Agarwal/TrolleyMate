import { useState } from "react";
import AgentTrace from "../../components/AgentTrace";
import Drawer from "../../components/Drawer";
import Skeleton from "../../components/Skeleton";
import BasketWorkspace from "../basket/BasketWorkspace";
import BudgetBar from "../basket/BudgetBar";
import GoalPicker from "../basket/GoalPicker";
import ChatPanel from "../intake/ChatPanel";
import ConstraintCard from "../intake/ConstraintCard";
import ConstraintsDrawer from "../intake/ConstraintsDrawer";
import StartPanel from "../intake/StartPanel";
import NegotiationPanel from "../negotiation/NegotiationPanel";
import { ShopProvider, useShop } from "./ShopContext";
import WorkingCard from "./WorkingCard";
import "./ShopPage.css";

const STAGES = ["Describe", "Confirm", "Basket", "Meals"] as const;

function Workspace() {
  const { state, trace, busy, error, clearError, negotiation, newSession, view, setView, focusChat, canCancelBuild, cancellingBuild, cancelBuild } = useShop();
  const [agentsOpen, setAgentsOpen] = useState(false);
  const [constraintsOpen, setConstraintsOpen] = useState(false);

  if (!state) {
    return (
      <div className="shop-loading">
        {error ? <div className="notice notice-beet">{error}</div> : <Skeleton rows={4} label="Opening your shop" />}
      </div>
    );
  }

  const draft = state.intake?.status === "draft";
  const hasBasket = !!state.basket && !draft;
  let stage = 0;
  if (draft) stage = 1;
  else if (state.constraints) stage = hasBasket && view === "meals" ? 3 : 2;

  const stageAction: (null | (() => void))[] = [
    () => focusChat(),
    state.constraints && !draft ? () => setConstraintsOpen(true) : null,
    hasBasket ? () => setView("basket") : null,
    hasBasket ? () => setView("meals") : null,
  ];

  return (
    <div className="shop">
      <aside className="shop-chat">
        <ChatPanel />
      </aside>

      <section className="shop-main" aria-busy={!!busy}>
        <header className="shop-head">
          <ol className="stage-rail" aria-label="Progress">
            {STAGES.map((label, i) => {
              const act = stageAction[i];
              const cls = i < stage ? "done" : i === stage ? "current" : "";
              return (
                <li key={label}>
                  <button
                    className={`stage ${cls}`}
                    onClick={act ?? undefined}
                    disabled={!act}
                    aria-current={i === stage ? "step" : undefined}
                    title={i === 1 && act ? "See your confirmed details" : undefined}
                  >
                    <span className="stage-n mono">{i < stage ? "✓" : i + 1}</span>
                    {label}
                  </button>
                </li>
              );
            })}
          </ol>
          <div className="row" style={{ "--gap": "8px" } as React.CSSProperties}>
            <button className="btn btn-sm agents-btn" onClick={() => setAgentsOpen(true)} aria-label={`See what the agents did (${trace.length} steps)`}>
              <span className={`pulse${busy ? " live" : ""}`} aria-hidden="true" />
              Agents
              <span className="mono agents-count">{trace.length}</span>
            </button>
            {(state.constraints || state.basket) && (
              <button className="btn btn-sm" onClick={newSession} disabled={!!busy}>
                New shop
              </button>
            )}
          </div>
        </header>

        {hasBasket && <BudgetBar />}
        {busy && <WorkingCard label={busy} onCancel={canCancelBuild ? cancelBuild : undefined} cancelling={cancellingBuild} />}

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
        {hasBasket && <BasketWorkspace />}
      </section>

      {agentsOpen && (
        <Drawer title="What your agents did" eyebrow="Behind the scenes" onClose={() => setAgentsOpen(false)}>
          <AgentTrace steps={trace} busy={busy} />
        </Drawer>
      )}
      {constraintsOpen && <ConstraintsDrawer onClose={() => setConstraintsOpen(false)} />}
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
