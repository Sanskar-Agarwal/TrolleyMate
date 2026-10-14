import { useShop } from "../shop/ShopContext";

const EXAMPLES = [
  { tag: "Week for two", text: "I have $100 for this week and cook two meals a day for us two." },
  { tag: "High protein", text: "$60 for 5 days, dinner only, high protein please." },
  { tag: "Family + coeliac", text: "Feed a family of four for the week on $150, three meals a day. One of us is coeliac." },
  { tag: "Tight budget", text: "$30 for the week, three meals a day for two of us." },
];

/** Stage 1 — nothing requested yet. */
export default function StartPanel() {
  const { chat, busy, focusChat } = useShop();
  return (
    <div className="start card">
      <span className="eyebrow">Step 1 · Describe your shop</span>
      <h2>
        What do you need <span className="hl">this week?</span>
      </h2>
      <p className="muted" style={{ maxWidth: "62ch" }}>
        Write it the way you'd say it. Your shopper picks out the budget, meals, people and anything you can't eat, adds
        the allergies saved for your household, and asks about anything it isn't sure of.
      </p>
      <div className="start-examples">
        {EXAMPLES.map((e) => (
          <button key={e.text} className="example" onClick={() => chat(e.text)} disabled={!!busy}>
            <span className="chip example-try">{e.tag}</span>
            <span>“{e.text}”</span>
          </button>
        ))}
      </div>
      <div className="row">
        <button className="btn btn-primary btn-lg" onClick={() => focusChat()}>
          Write my own
        </button>
        <span className="small muted">
          or press <kbd>/</kbd>
        </span>
      </div>
    </div>
  );
}
