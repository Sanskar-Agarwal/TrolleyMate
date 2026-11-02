# Safety demo segment (KAN-24, about 3 minutes)

Shows the AI Nutrition & Compliance agent's two safety guarantees:

- **Hidden allergens are refused**, and the refusal names what was hidden (1.2.10: hidden ingredients and
  composite products, not product names or labels).
- **Uncertainty stays unresolved, not presented as safe.** An item whose safety can't be confirmed is withheld
  and escalated. While the dietitian can't decide, it stays out of the basket and its total (UC-06
  extension 2a; UC-06.1 failure scenario: "never presented as safe without a human decision").

Specials are priced by weekday, so the basket changes from day to day. Every step below is checked for all
seven weekdays by [`test_safety_demo.py`](../backend/tests/test_safety_demo.py). It also works in offline agent
mode, so a campus VPN or LLM outage doesn't affect it.

**Before presenting:** use a disposable demo database with fresh seed data and no saved dietitian approvals.
Run `python -m app.seed --reset` from `backend` with its virtual environment active only against
that disposable database; this deletes its existing data. With the historical
[demo script](DEMO_SCRIPT.md), this segment takes the place of step 5, and step 7 there releases the item
held here.

| # | Do | You'll see | Say (criterion) |
|---|---|---|---|
| 1 | Sign in as **Alex**. Type *"$120 for the week, two meals a day"* → **Confirm constraints** → **Balanced** → **Build my basket**. | The constraint card locks *Lactose · moderate* (Alex) and *Tree nuts · severe* (Jamie). | The household profile applies to every shop, and the request can't relax it. (C1) |
| 2 | Expand **products left out for safety**. | Full Cream Milk, Almond Milk and others, each with its reason. | Screened before the optimiser runs: a violation never reaches the solver. (C1) |
| 3 | Chat *"add honey muesli bars"*. | *Honey Muesli Bars 6pk isn't safe for your household: contains whey powder (lactose); contains almonds (tree nuts).* | Hidden allergens: nothing in the name says dairy or nuts. The agent reads every ingredient. (C2) |
| 4 | Chat *"add sugar free mints"* (no hyphen). | *Sugar-free Mints 35g isn't safe ...: contains sweetener (966) (lactose).* | Hidden behind an E-number: sweetener 966 is lactitol, made from lactose. (C2) |
| 5 | Chat *"add basil pesto"*. | *Basil Pesto 190g isn't safe ...: contains pine nuts (tree nuts).* | Cascading check through a composite ingredient (8.4 `getComposition()`). Nothing else was added in its place. (C1) |
| 6 | Point at **Value Chicken Schnitzel 1kg**: *Held for review*, *On hold +$5.60*, **Accept basket** disabled. | *Waiting on a dietitian: Value Chicken Schnitzel 1kg ...* | Its ingredient list is missing from the retailer feed. At 40% confidence, below the 95% threshold, it is withheld and escalated (human approval gate, Stage 1 §4.2). (C2) |
| 7 | Sign out → **Dr Sam Patel** → open the schnitzel case → *Request info*: *"Is there a full ingredient list?"* Don't decide. | The agent answers that the list isn't in the feed. The case stays under review. | The dietitian can't confirm it either, so no decision is made (UC-06.1 extension 5a). (C2) |
| 8 | Sign in as **Alex** again. | Still held, still not in the total, **Accept** still disabled. | Unresolved uncertainty is never presented as safe. (C1) |
| 9 | *(Optional)* **Maya** → **Agent audit**, basket filter. | `raise_escalation` at 40% confidence, with the reason. | Every safety decision is recorded and attributable (1.2.14). (C2) |

**Optional extra, hidden gluten (+1 minute):** start a new shop with the *Family favourites* starter (*"Feed a
family of four for the week on $150, three meals a day. One of us is coeliac."*) and expand **left out for safety**:
*Pork Sausages 500g: contains wheat rusk (gluten)*, *Pearl Barley 500g: contains barley (gluten)*, *Couscous
500g: contains durum wheat semolina (gluten)*.

**If asked how we know it works:** the segment runs as `pytest tests/test_safety_demo.py` for every weekday.
The 42-case safety evaluation runs as `pytest tests/test_agent_evaluation.py`, with its observed results in
[`evidence/agent-evaluation.md`](evidence/agent-evaluation.md).

**After a rehearsal:** Sam's request for information stays on the case. Reset only your disposable
demo database if you need to repeat the initial scenario.
