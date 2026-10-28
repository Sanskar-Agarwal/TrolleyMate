import { mealPlans } from "../../api/endpoints";
import { useShop } from "../shop/ShopContext";
import "./mealplan.css";

/** UC-08: a day-by-day plan cooked only from what's in the basket. */
export default function MealPlanView() {
  const { state, run, busy, setView } = useShop();
  const basket = state!.basket!;
  const plan = state!.meal_plan;
  const planning = busy === "Planning meals from your basket";
  const generate = () =>
    run("Planning meals from your basket", () => mealPlans.generate(basket.id), {
      toast: (r) => [`Meal plan ready: ${r.meal_plan.planned} of ${r.meal_plan.requested} meals`],
    });

  if (basket.status !== "accepted") {
    return (
      <section className="card stack" style={{ maxWidth: 720 }}>
        <span className="eyebrow">Step 4 · Meals</span>
        <h2>Your basket comes first</h2>
        <p className="muted">{basket.status === "pending_review"
          ? "Some items are waiting for dietary review. Once that is resolved, review and accept your basket to plan meals."
          : "Review the products, quantities and total, then accept your basket. Your meal plan will use only those ingredients."}</p>
        <div><button className="btn btn-primary" onClick={() => setView("basket")}>Review my basket</button></div>
      </section>
    );
  }

  if (!plan) {
    return (
      <div className="card stack" style={{ maxWidth: 720 }}>
        <span className="eyebrow">Step 4 · Meals</span>
        <h2>Turn your accepted basket into meals</h2>
        <p className="muted">
          Recipes use only what's in your basket, share packs across meals so less goes to waste, and assume you have salt,
          pepper and oil at home.
        </p>
        <div className="row">
          <button className="btn btn-primary" onClick={generate} disabled={!!busy}>
            {planning ? "Planning meals…" : "Plan my meals"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="stack meal-plan" style={{ "--gap": "18px" } as React.CSSProperties}>
      <div className="spread">
        <div className="stack" style={{ "--gap": "4px" } as React.CSSProperties}>
          <span className="eyebrow">Meal plan</span>
          <h2>
            {plan.planned} of {plan.requested} meals planned
          </h2>
        </div>
        <button className="btn btn-sm" onClick={generate} disabled={!!busy}>
          {planning ? "Planning meals…" : "Re-plan"}
        </button>
      </div>
      <div className={`notice ${plan.planned === plan.requested ? "notice-produce" : "notice-amber"}`} role="status">
        <span>
          <strong>{plan.planned === plan.requested
            ? "Every requested meal is covered."
            : `${plan.requested - plan.planned} ${plan.requested - plan.planned === 1 ? "meal still needs" : "meals still need"} ingredients.`}</strong>{" "}
          Each planned meal serves your household. Portions are allocated across the whole plan, so ingredients are not counted twice.
        </span>
      </div>
      {plan.total_minutes != null && <p className="small muted">
        Estimated cooking time: {plan.total_minutes} min across planned meals.
        {plan.goal === "fastest_cook" && " Each slot prioritises the quickest recipe available in your basket."}
        {plan.goal === "least_waste" && " Recipes prioritise ingredients nearing the end of their shelf life."}
        {plan.portions_per_meal != null && ` Ingredients are allocated for ${plan.portions_per_meal} adult-equivalent portions per meal.`}
      </p>}
      <p className="small muted">Assumed at home: {plan.assumed_at_home.join(", ")}. Perishable ingredients are scheduled within their recorded shelf life, starting on Day 1.</p>
      {plan.reused.length > 0 && (
        <p className="small"><strong>Shared across meals:</strong> {plan.reused.join(", ")}. These packs are used more than once within their available quantities.</p>
      )}
      {plan.summary && <p className="basket-summary">{plan.summary}</p>}

      <div className="week">
        {plan.days.map((d) => (
          <section key={d.day} className="day">
            <h4 className="mono">Day {d.day}</h4>
            {d.meals.length === 0 && <p className="small muted">No meal requested for this day.</p>}
            {d.meals.map((m, i) => (
              <article key={i} className={`meal${m.recipe ? "" : " gap"}`}>
                <span className="eyebrow">{m.slot}</span>
                {m.recipe ? (
                  <>
                    <strong>{m.recipe}</strong>
                    <span className="small muted">
                      {m.minutes} min · {m.servings} servings · {m.uses?.join(", ")}
                    </span>
                    {!!m.ingredients?.length && <span className="small muted">Allocated: {m.ingredients.map((ingredient) => `${ingredient.name} (${ingredient.servings} serves)`).join(", ")}</span>}
                    {!!m.optional?.length && <span className="small muted">Also included: {m.optional.join(", ")}</span>}
                  </>
                ) : (
                  <>
                    <strong>Not enough in the basket</strong>
                    <span className="small">Suggested meal: {plan.missing.find((gap) => gap.day === d.day && gap.slot === m.slot)?.suggested_recipe ?? "No matching recipe"}</span>
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
          <div className="stack" style={{ "--gap": "8px" } as React.CSSProperties}>
            <strong>Suggested additions for missing ingredients</strong>
            <ul className="meal-additions">
              {plan.suggested_additions.map((s) => <li key={s.for}>{s.product} <span className="muted">for {s.for}</span></li>)}
            </ul>
            <p>These are suggestions only and may not cover every gap. Nothing has been added to your basket. Ask your shopper to change the basket, then review and accept it again before re-planning.</p>
          </div>
        </div>
      )}
      {!!plan.expired_unused?.length && <div className="notice notice-amber"><span>Not scheduled beyond shelf life: {plan.expired_unused.map((l) => `${l.name} (${l.servings_left} serves)`).join(", ")}. These are not counted as usable leftovers.</span></div>}
      {plan.leftovers.length > 0 && (
        <p className="small muted">
          Left over at the end of the plan: {plan.leftovers.map((l) => `${l.name} (${l.servings_left} serves)`).join(", ")}.
        </p>
      )}
    </div>
  );
}
