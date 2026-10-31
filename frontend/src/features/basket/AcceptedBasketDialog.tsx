import { useEffect, useRef } from "react";

export default function AcceptedBasketDialog({ busy, error, onClose, onPlaceOrder, onMealPlan }: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onPlaceOrder: () => void;
  onMealPlan: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current!;
    node.showModal();
    return () => node.close();
  }, []);

  return (
    <dialog ref={dialog} className="accepted-basket-dialog" aria-labelledby="accepted-basket-title"
      aria-describedby="accepted-basket-description" onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}>
      <div className="stack">
        <div className="spread">
          <span className="chip chip-produce">Accepted</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose} disabled={busy} aria-label="Close next steps">Close</button>
        </div>
        <h2 id="accepted-basket-title">Your basket is ready</h2>
        <p id="accepted-basket-description">What would you like to do next?</p>
        <div className="accepted-basket-options">
          <div className="card-flat stack">
            <h3>Ready to shop?</h3>
            <p className="small muted">Finish this demo shop and return to a fresh shopping request.</p>
            <button className="btn btn-primary" onClick={onPlaceOrder} disabled={busy}>
              {busy ? "Starting a new shop…" : "Place order"}
            </button>
          </div>
          <div className="card-flat stack">
            <h3>Plan what to cook</h3>
            <p className="small muted">Open the meal planner using the ingredients in your accepted basket.</p>
            <button className="btn btn-primary" onClick={onMealPlan} disabled={busy}>Make meal plan</button>
          </div>
        </div>
        <p className="small muted">Demo only: no order is sent to a retailer and no payment is taken.</p>
        {error && <p className="notice notice-amber" role="alert">{error}</p>}
      </div>
    </dialog>
  );
}
