import { mealPlans } from "../../api/endpoints";
import { useShop } from "../shop/ShopContext";
import "./mealplan.css";

/** UC-08 — a day-by-day plan cooked only from what's in the basket. */
export default function MealPlanView() {
  const { state, run, busy } = useShop();
  const basket = state!.basket!;
  const plan = state!.meal_plan;
  const generate = () =>
    run("Planning meals from your basket", () => mealPlans.generate(basket.id), {
      toast: (r) => [`Meal plan ready: ${r.meal_plan.planned} of ${r.meal_plan.requested} meals`],
    });

  if (!plan) {
    return (
      <div className="card stack" style={{ maxWidth: 720 }}>
        <span className="eyebrow">Step 4 · Meals</span>
        <h2>Turn this basket into a week of meals</h2>
        <p className="muted">
          Recipes use only what's in your basket, share packs across meals so less goes to waste, and assume you have salt,
          pepper and oil at home.
        </p>
        <div className="row">
          <button className="btn btn-primary" onClick={generate} disabled={!!busy}>
            Plan my meals
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="stack" style={{ "--gap": "18px" } as React.CSSProperties}>
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">Meal plan</span>
          <h2>
            {plan.planned} of {plan.requested} meals planned
          </h2>
        </div>
        <button className="btn btn-sm" onClick={generate} disabled={!!busy}>
          Re-plan
        </button>
      </div>
      {plan.summary && <p className="basket-summary">{plan.summary}</p>}

      <div className="week">
        {plan.days.map((d) => (
          <section key={d.day} className="day">
            <h4 className="mono">Day {d.day}</h4>
            {d.meals.map((m, i) => (
              <article key={i} className={`meal${m.recipe ? "" : " gap"}`}>
                <span className="eyebrow">{m.slot}</span>
                {m.recipe ? (
                  <>
                    <strong>{m.recipe}</strong>
                    <span className="small muted">
                      {m.minutes} min · {m.uses?.join(", ")}
                    </span>
                  </>
                ) : (
                  <>
                    <strong>Not enough in the basket</strong>
                    <span className="small muted">Needs: {m.missing?.join(", ")}</span>
                  </>
                )}
              </article>
            ))}
          </section>
        ))}
      </div>

      {plan.suggested_additions.length > 0 && (
        <div className="notice notice-amber">
          <span>
            <strong>To cook the remaining meals</strong> you'd also need:{" "}
            {plan.suggested_additions.map((s) => `${s.product} (${s.for})`).join(", ")}. These aren't added automatically — ask your
            shopper to add them if you want.
          </span>
        </div>
      )}
      {plan.leftovers.length > 0 && (
        <p className="small muted">
          Left over at the end of the plan: {plan.leftovers.map((l) => `${l.name} (${l.servings_left} serves)`).join(", ")}.
        </p>
      )}
    </div>
  );
}
