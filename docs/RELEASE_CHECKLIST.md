# KAN-6 release checklist and seven-minute demo

This is a run sheet and acceptance checklist, not a record of a completed team rehearsal.
**Group rehearsal, agreed contributions, feedback responses and final release sign-off are
Pending human action.** Technical test results do not complete those activities.

Status reconciliation, **29 October 2026**: KAN-6 is marked Done in Jira. No completed
all-member rehearsal, contribution agreement or final sign-off record was found in the
repository audit. The human checks below remain unverified until the team links the actual
records; the Jira status alone does not fill them in.

Use Stage 1 requirements **1.2.1–1.2.15** as the acceptance baseline and
[TEAM_GUIDE.md](TEAM_GUIDE.md) for ownership. The original backlog included stretch work;
do not treat every backlog suggestion as an original requirement. Use
[README verification](../README.md#verification) for the latest tested version,
[UAT_2026-10-28.md](UAT_2026-10-28.md) for the dated browser/live-model evidence, and
[JOURNEY_VERIFICATION.md](JOURNEY_VERIFICATION.md#4-requirement-traceability) for the code/test
map. Historical pass statements are not a substitute for checking the release candidate.

## People and agent roles

These presentation assignments follow the team guide; each member must confirm their own
contribution and speaking slot during rehearsal.

| Member | Explain and demonstrate | Agent role |
|---|---|---|
| Sanskar | Intake, five optimisation goals, accepted-basket meal plans | AI Personal Shopper |
| Peter | Infeasibility options and substitution trade-offs | AI Personal Shopper |
| Chester | Retailer prices, units, savings and conversational basket edits | AI Market Analyst, coordinated by the shopper |
| Reyon | Allergen cascade, nutrition coverage and preference memory | AI Nutrition & Compliance |
| Maaz | Profiles, review workflow, explanations, audit and release operation | Independent AI Technical Manager |

The three core agents are Personal Shopper, Market Analyst and Nutrition & Compliance.
The Technical Manager provides independent audit and oversight. The dietitian account is
the human review role; it is not a fourth core shopping agent.

## Before starting the timer

- Select one release commit and record its full SHA, app URL, image tag or source archive,
  startup method and actual model mode. Follow [README](../README.md#quick-start) and
  [CI_CD.md](CI_CD.md); a published image is not a hosted application.
- Use an isolated demo database. Do not reset a shared database to prepare this presentation.
  Check `/api/health`, sign-in, compiled frontend assets and the visible model-mode badge.
- Open the shopper, dietitian and founder views in separate browser profiles, signed in as
  Alex, Dr Sam Patel and Maya. Use the seeded demo accounts documented in the README.
- Rehearse the exact request below on the selected version. Prepare a second infeasible shop
  and a review case through the normal app workflow. Clearly label these as prepared cases.
  The optimiser may choose different products; never promise a particular held item.
- Keep evidence for edge cases ready: third correction/form, cancellation, failed-save retry,
  incomplete price data, insufficient price history and partial meal coverage. A seven-minute
  presentation samples the journey; the acceptance matrix below covers all requirements.
- Prefer mock mode for a predictable timed run. A live model API is optional for operating
  the demo. If used, verify access beforehand and report live, degraded or offline mode
  accurately. Changed-prompt live-test evidence belongs in the UAT record, not an assumed pass.

## Timed run sheet — 7:00 total

| Time | Presenter and action | What the audience should see |
|---|---|---|
| 0:00–0:30 | **Maaz:** show the release/version record and mode badge. Open Alex's household; point out lactose and tree-nut restrictions and a saved preference. | Profile rules are mandatory; preferences are editable soft choices. Name the three core agents and independent manager. |
| 0:30–1:30 | **Sanskar:** enter “I have $100 for this week, two meals a day for us two. High protein please.” Answer “120g”, apply one budget correction to $90, inspect locked rules, then confirm. Point to prepared third-correction/form and cancellation evidence. | The agent asks about ambiguity. Drafts remain inactive until confirmation; clarification does not count as a correction. |
| 1:30–2:15 | **Sanskar:** show all five goals, choose Balanced and build. Open the agent activity feed, priced items, budget total and excluded products. | Market Analyst supplies prices; Compliance screens; the deterministic solver builds under the confirmed constraints; the chosen goal is recorded. |
| 2:15–3:05 | **Chester:** compare stores and change the named baseline. Show split-store totals, unit prices and buy-timing advice or its absence. Make one valid chat edit to an item actually present and show the before/after result. | Savings have a baseline; missing data is visible. An edit preserves mandatory rules and the budget. Timing advice does not change the basket. |
| 3:05–3:50 | **Reyon:** open nutrition coverage and an excluded/held item's evidence. Show the saved-preference controls. Explain why an uncertain item cannot be accepted and why a nutrition exception never overrides an allergy. | Independent dietary screening and nutrition checks; shopper-controlled preference memory. Use prepared evidence if this build has no held item or gap. |
| 3:50–4:30 | **Maaz:** switch to the prepared dietitian case, request information and apply the documented review decision. Return to its shopper view; show the updated status and explanation. | Human review is required before withheld stock is released. Audit facts and basket state follow the decision. Do not describe a prepared case as created by the current build. |
| 4:30–5:15 | **Peter:** propose a substitute and read its trade-off; decline it and show the retained basket. Open the prepared “$30 for the week, three meals a day for two of us” shop and show the computed budget/coverage options. | Substitution is a choice; declined swaps are remembered. Infeasibility is explained with options and mandatory restrictions retained. |
| 5:15–6:10 | **Sanskar:** return to the current shopper basket, resolve any outstanding gate, accept it and generate meals. Show daily slots, quantities/reuse, pantry assumptions and any missing meals/additions. | Only accepted, reviewed basket stock supplies meals. Missing ingredients are recommendations, never silent purchases. If a gate cannot be resolved in time, show the labelled prepared accepted-basket example. |
| 6:10–7:00 | **Maaz:** open Maya's audit view, filter a session/agent and inspect recorded rationale and model attribution. Show the release's CI/UAT evidence and state the limits below. | The manager's oversight is separate from the three core agents. Close with the actual release status and any pending human decisions. |

If a call stalls, name the mode or failure and move to the labelled prepared evidence.
Record the interruption in rehearsal feedback; do not silently count an unexecuted step as passed.

## All 15 requirements: release acceptance evidence

Each row needs a linked test, UAT result or recorded demonstration for the **selected release
commit**. The matrix defines checks; it does not claim that each check has been completed.

| Requirement | Evidence to check before acceptance |
|---|---|
| 1.2.1 Intake | Extraction, ambiguity, locked rules, third-correction form, confirm-only activation, cancellation and save-failure retry preserve the previous set. |
| 1.2.2 Optimisation | All five goals are selectable and recorded; priced basket stays within budget and mandatory restrictions for each goal. |
| 1.2.3 Meal plans | Acceptance gate, household portions and meal count, quantity-limited reuse, only stated pantry assumptions, explicit gaps and optional additions. |
| 1.2.4 Negotiation | An infeasible request returns computed extra-budget and achievable-coverage choices; applying a choice rebuilds without dropping mandatory rules. |
| 1.2.5 Substitution | Safe candidate and stated trade-off, explicit accept/decline, declined-swap memory and no-alternative handling. |
| 1.2.6 Buy timing | Advice is grounded in recorded history; insufficient history produces no prediction, daily staples are skipped, and waiting beyond shelf life is refused; basket is unchanged. |
| 1.2.7 Ingestion/units | Multiple retailer records, comparable unit prices and explicit missing/unreliable data handling; data provenance is stated. |
| 1.2.8 Savings | Named baseline, correct totals/dollar/percentage savings, split-store comparison and no unsupported savings claim for incomplete quotes. |
| 1.2.9 Chat editing | Requested edit or targeted clarification, visible resulting change, budget/mandatory-rule preservation and failed-edit rollback. |
| 1.2.10 Allergens | Ingredient/composite checks, household restrictions, excluded violations and withheld/escalated uncertainty. |
| 1.2.11 Nutrition | Household-scaled coverage, explicit per-person targets, repairs/shortfalls and recorded shopper acceptance of an eligible nutrition exception. |
| 1.2.12 Preferences | Owner can view/change/forget saved preferences; later shops apply them while mandatory dietary rules take precedence. |
| 1.2.13 Profiles | Authorised account/profile access, household member and restriction editing, retained data after failed saves and correct later-session use. |
| 1.2.14 Explanations/audit | Basket/item explanations reference recorded evidence; decisions, rationale and model attribution are inspectable by the authorised role. |
| 1.2.15 Human review | Review assignment, evidence/information exchange, decision application, withheld-stock gate and traceable outcome. |

## KAN-6 release gate

KAN-6 requires the full agent journey to be rehearsed with every member explaining their work,
evidence for all 15 requirements, recorded limitations and responses to feedback, and agreement
on final contributions and the release by all members.

- [x] Technical verification is recorded for main `947a59c`: 416 backend tests and 57 frontend
  tests in the integration checks; [main CI run 40806441408](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/runs/40806441408)
  passed and published the Docker image. [README verification](../README.md#verification)
  links the current record; the [28 October UAT](UAT_2026-10-28.md) remains a separate dated run.
  These checks establish neither group rehearsal nor human approval.
- [ ] Complete the 15-row acceptance matrix with current evidence; link the browser UAT record.
- [ ] **Pending human action — group rehearsal:** all five members attend, explain their work,
  time the run and record actual attendees, duration, failed steps and substitutions of prepared evidence.
- [ ] **Pending human action — feedback and responses:** record each real comment, its source,
  the responsible member, resolution or accepted limitation, and retest/evidence link.
- [ ] **Pending human action — contributions:** each member reviews and agrees the final
  contribution statement. Ownership in the team guide is not proof of work performed or agreement.
- [ ] **Pending human action — release sign-off:** every member agrees the exact commit/artifact,
  known limitations and remaining actions. Record names and dates only after that agreement.
- [ ] Confirm the final submission package starts using its supplied instructions and excludes
  credentials. Record its exact commit, archive checksum, extraction/run result, contribution form
  and submission location after human release approval (KAN-30).

| Human record | Status / fields to complete |
|---|---|
| Rehearsal | **Pending human action:** date, attendees, commit, mode, actual duration, evidence link |
| Feedback responses | **Pending human action:** comment, source, owner, response, retest or accepted limitation |
| Sanskar contribution and release agreement | **Pending human action:** agreed contribution, approval date |
| Peter contribution and release agreement | **Pending human action:** agreed contribution, approval date |
| Chester contribution and release agreement | **Pending human action:** agreed contribution, approval date |
| Reyon contribution and release agreement | **Pending human action:** agreed contribution, approval date |
| Maaz contribution and release agreement | **Pending human action:** agreed contribution, approval date |
| Final release | **Pending human action:** commit SHA, tag/archive/image, unresolved items, all-member approval record |

## Limits to state plainly

- The four-retailer demo catalogue and recorded price history are demonstration data. The
  simulated partner feed does not establish current real-store prices, stock or checkout capability.
- Basket cooking-time and waste objectives use product-level estimates: preparation time per
  serving and pack servings/perishability. Meal selection uses recipe minutes and stock expiry;
  this is not a joint proof of the globally fastest or lowest-waste shopping-and-cooking schedule.
- Age-based portion factors are prototype estimates. Explicit per-person nutritional targets
  must retain the shopper's stated headcount semantics.
- Recipes come from the bundled recipe set. Stock, expiry and recipe compatibility can leave
  gaps; those gaps and suggested additions must remain visible. Only salt, pepper and cooking
  oil are assumed at home. Recipe cards are not a complete generated cooking-instruction service.
- Live model APIs require separately configured access and can fail or rate-limit. Mock mode
  runs without credentials; fallback is labelled. Do not present mock or fallback results as live AI.
- Container publication supplies a runnable image; hosting, final submission and all-member
  agreement are separate activities. This checklist records no completed rehearsal or team sign-off.
