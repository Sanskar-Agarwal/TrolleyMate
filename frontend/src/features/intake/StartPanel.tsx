import { useShop } from "../shop/ShopContext";

const EXAMPLES = [
  { tag: "Week for two", budget: "$100", detail: "7 days · 2 people", text: "I have $100 for this week and cook two meals a day for us two." },
  { tag: "High protein", budget: "$60", detail: "5 days · Dinner", text: "$60 for 5 days, dinner only, high protein please." },
  { tag: "Family favourites", budget: "$150", detail: "7 days · Gluten-free", text: "Feed a family of four for the week on $150, three meals a day. One of us is coeliac." },
  { tag: "Make it stretch", budget: "$30", detail: "7 days · 2 people", text: "$30 for the week, three meals a day for two of us." },
];

export default function StartPanel() {
  const { busy, focusChat, chat } = useShop();
  return (
    <div className="start">
      <section className="start-hero" aria-labelledby="start-title">
        <span className="eyebrow">A little planning. A better shop.</span>
        <h1 id="start-title">Good food.<br /><span className="hl">Your budget.</span></h1>
        <p className="start-intro">Tell us who you're feeding, what you enjoy and what you want to spend. We'll help you put it all together.</p>
        <div className="start-actions">
          <button className="btn btn-primary btn-lg" onClick={() => focusChat()} disabled={!!busy}>
            Plan my shop <span aria-hidden="true">↗</span>
          </button>
          <span className="small muted">Start with a message <kbd>/</kbd></span>
        </div>
        <div className="start-assurance"><span aria-hidden="true">✓</span> Review your details before we build your basket.</div>
      </section>

      <section aria-labelledby="examples-title" className="start-inspiration">
        <div className="spread">
          <h2 id="examples-title">Need a starting point?</h2>
          <span className="small muted">Choose one and make it yours</span>
        </div>
        <div className="start-examples">
          {EXAMPLES.map((e) => (
            <button key={e.tag} className="example" onClick={() => void chat(e.text)} disabled={!!busy} aria-label={`Use ${e.tag} example: ${e.text}`}>
              <span className="example-top"><strong>{e.tag}</strong><span className="example-arrow" aria-hidden="true">↗</span></span>
              <span className="example-budget">{e.budget}<span className="small muted"> budget</span></span>
              <span className="example-detail">{e.detail}</span>
              <span className="example-copy">{e.text}</span>
              <span className="example-use">Use this idea <span aria-hidden="true">→</span></span>
            </button>
          ))}
        </div>
      </section>
      <p className="start-footnote">Your household's saved dietary restrictions are included when you plan.</p>
    </div>
  );
}
