import { useShop } from "../shop/ShopContext";

const EXAMPLES = [
  "I have $100 for this week and cook two meals a day for us two.",
  "$60 for 5 days, dinner only, high protein please.",
  "Feed a family of four for the week on $150, three meals a day. One of us is coeliac.",
  "$30 for the week, three meals a day for two of us.",
];

/** Stage 1 — nothing requested yet. */
export default function StartPanel() {
  const { chat, busy } = useShop();
  return (
    <div className="start card">
      <span className="eyebrow">Step 1 · Describe your shop</span>
      <h2>What do you need this week?</h2>
      <p className="muted">
        Write it the way you'd say it. Your shopper pulls out the budget, meals, people and restrictions, adds the allergies
        saved in your household, and asks about anything it can't pin down.
      </p>
      <div className="start-examples">
        {EXAMPLES.map((e) => (
          <button key={e} className="example" onClick={() => chat(e)} disabled={!!busy}>
            <span className="mono small muted">Try</span>
            <span>“{e}”</span>
          </button>
        ))}
      </div>
    </div>
  );
}
