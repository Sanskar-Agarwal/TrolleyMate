import { useEffect, useState } from "react";

// What the agents actually do on a basket build (see backend workflows/basket_builder.py),
// in shopper language. Shown in order while the request is in flight.
const BUILD_STEPS = [
  "Checking prices at 3 stores",
  "Removing anything unsafe for your household",
  "Finding the best combination for your budget",
  "Double-checking every item",
  "Writing up why it picked each one",
];

/** A friendly "working on it" sticker while the agents are busy. */
export default function WorkingCard({ label }: { label: string }) {
  const building = label === "Building your basket";
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!building) return;
    setStep(0);
    const id = window.setInterval(() => setStep((s) => Math.min(s + 1, BUILD_STEPS.length - 1)), 700);
    return () => window.clearInterval(id);
  }, [building]);

  return (
    <div className="working" role="status" aria-live="polite">
      <span className="working-trolley" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="30" height="30">
          <path d="M5 8h3.4l2.6 12h11.4L25 11.5H10" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="13" cy="25" r="2" fill="currentColor" />
          <circle cx="21" cy="25" r="2" fill="currentColor" />
        </svg>
      </span>
      <div className="stack" style={{ "--gap": "6px", flex: 1 } as React.CSSProperties}>
        <strong>{label}…</strong>
        {building && (
          <ol className="working-steps">
            {BUILD_STEPS.map((s, i) => (
              <li key={s} className={i < step ? "done" : i === step ? "now" : ""}>
                {s}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
