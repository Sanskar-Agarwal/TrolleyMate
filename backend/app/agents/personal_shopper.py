"""«supervisor» PersonalShopperAgent — owns the user-facing workflow and coordinates the
worker agents (Figure 4.2). Each operation delegates to a workflow module so the
team can work on use cases independently.

Control is hybrid (Section 4.1):
  - the primary basket path is workflow-controlled (`orchestrate`)
  - chat messages are supervisor-controlled: the LLM classifies intent, then this
    agent decides which workflow / worker handles it (`handle_message`)
"""

from __future__ import annotations

from datetime import datetime

from app.agents.base import Agent
from app.domain import Basket, BasketItem, ShoppingRequest, ShoppingSession, Substitution
from app.workflows import basket_builder, basket_editing, intake, meal_planning, negotiation, substitution


class PersonalShopperAgent(Agent):
    role_name = "AI Personal Shopper"
    key = "personal_shopper"
    max_replan_attempts = 3

    # UC-01
    def extract_constraints(self, s: ShoppingSession, raw: str) -> ShoppingRequest:
        return intake.start(self, s, raw)

    def clarify(self, req: ShoppingRequest, answer: str) -> ShoppingRequest:
        return intake.clarify(self, req, answer)

    def correct(self, req: ShoppingRequest, *, text: str | None = None, patch: dict | None = None) -> ShoppingRequest:
        return intake.correct(self, req, text=text, patch=patch)

    def submit_form(self, req: ShoppingRequest, form: dict) -> ShoppingRequest:
        return intake.submit_form(self, req, form)

    def confirm(self, req: ShoppingRequest):
        return intake.confirm(self, req)

    def cancel(self, req: ShoppingRequest) -> ShoppingRequest:
        return intake.cancel(self, req)

    # UC-02 (+ UC-03 on infeasibility)
    def orchestrate(self, s: ShoppingSession, goal: str | None = None) -> basket_builder.BuildOutcome:
        return basket_builder.build(self, s, goal)

    def negotiate(self, s: ShoppingSession, **choice) -> basket_builder.BuildOutcome:
        return negotiation.apply(self, s, **choice)

    # UC-04
    def find_substitute(self, item: BasketItem, reason: str = "user_requested") -> Substitution:
        return substitution.propose(self, item, reason)

    def accept_substitution(self, sub: Substitution) -> Basket:
        return substitution.accept(self, sub)

    def reject_substitution(self, sub: Substitution) -> Basket:
        return substitution.reject(self, sub)

    # UC-08
    def plan_meals(self, b: Basket):
        return meal_planning.generate(self, b)

    # UC-09
    def edit_basket(self, b: Basket, text: str) -> dict:
        return basket_editing.edit(self, b, text)

    # Supervisor-controlled routing for free-text chat
    def handle_message(self, s: ShoppingSession, text: str) -> dict:
        state = self.perceive(s)
        decision = self.think("classify_intent", {"text": text, "state": state})
        intent = decision.data["intent"]
        self.log("route_message", f"Intent: {intent}", confidence=decision.data.get("confidence"), session_id=s.id, llm=decision)
        _remember(s, "user", text)

        basket = basket_builder.current_basket(self, s)
        draft = next((r for r in reversed(s.requests) if r.status == "draft"), None)
        response: dict = {"intent": intent, "reply": decision.data.get("reply", "")}

        if intent == "clarify_answer" and draft is not None:
            req = self.clarify(draft, text)
            response.update(kind="intake", intake=intake.state(req), reply=_intake_reply(req))
        elif intent == "new_request" or (intent == "clarify_answer" and draft is None) or (basket is None and intent in ("edit_basket", "explain", "meal_plan", "compare_prices")):
            req = self.extract_constraints(s, text)
            response.update(kind="intake", intake=intake.state(req), reply=_intake_reply(req))
        elif intent == "edit_basket":
            result = self.edit_basket(basket, text)
            response.update(kind="edit", edit={k: v for k, v in result.items() if k != "basket"})
            if result["status"] == "ok":
                response["basket_id"] = result["basket"].id
                response["reply"] = "Done — " + ", ".join(result["applied"]) + ". " + basket_editing.describe_diff(result["diff"]) + (
                    " " + " ".join(result["conflicts"]) if result.get("conflicts") else "")
            else:
                response["reply"] = result.get("question") or result.get("message")
        elif intent == "explain":
            explanation = self.ctx.manager.explain_for(basket)
            response.update(kind="explain", reply=explanation["text"])
        elif intent == "meal_plan":
            plan = self.plan_meals(basket)
            response.update(kind="meal_plan", meal_plan_id=plan.id, reply=plan.summary)
        elif intent == "price_question":
            response.update(kind="price", reply=self._answer_price_question(basket, text))
        elif intent == "edit_household":
            response.update(kind="household", reply=self._edit_household(s, text, has_basket=basket is not None))
        elif intent == "compare_prices":
            report = self.ctx.analyst.compare(basket)
            response.update(kind="compare", reply=report["insight"] or "I couldn't price enough items to compare stores.")
        else:
            reply = self.think("chat_reply", {"text": text, "state": state})
            response.update(kind="chat", reply=reply.data)

        _remember(s, "assistant", response["reply"])
        return response


    # "Why is the chicken cheaper at ValueMart?" — one product, from recorded quotes (1.2.8)
    def _answer_price_question(self, basket: Basket | None, text: str) -> str:
        from app.services.catalogue import find_products, match_item

        item = match_item(basket, text) if basket is not None else None
        product = item.product if item is not None else next(iter(find_products(self.db, text, limit=1)), None)
        if product is None:
            return "Which product do you mean? For example: \"why is the chicken cheaper at ValueMart?\""
        return self.ctx.analyst.explain_difference(product, asked_about=text)

    # "Jamie is now vegetarian" — chat can add to the profile; removing stays on the Household page (1.2.13)
    def _edit_household(self, s: ShoppingSession, text: str, *, has_basket: bool) -> str:
        from app.domain import DietaryProfile, HouseholdMember
        from app.services.dietary_rules import RESTRICTION_RULES, label, normalise_restriction
        from app.services.session_state import household_of

        household = household_of(self.db, s)
        result = self.think("household_edit", {"text": text, "members": [m.name for m in household.members]})
        done, refused = [], []
        for op in result.data.get("operations", []):
            rid = normalise_restriction(op["restriction"]) if op.get("restriction") else None
            if rid is not None and rid not in RESTRICTION_RULES:
                refused.append(f"I don't know the restriction \"{op['restriction']}\".")
                continue
            kind = RESTRICTION_RULES[rid]["kind"] if rid else None
            severity = op.get("severity") or ("moderate" if kind == "intolerance" else "severe")
            if op["op"] == "remove":
                refused.append("To remove a member or an allergy, use the Household page so you can see exactly what changes.")
            elif op["op"] == "add_member":
                if any(m.name.lower() == op["member"].lower() for m in household.members):
                    refused.append(f"{op['member']} is already in your household.")
                    continue
                member = HouseholdMember(name=op["member"], age_group=op.get("age_group") or "adult")
                if rid:
                    member.dietary_profiles.append(DietaryProfile(restriction=rid, kind=kind, severity=severity))
                household.add_member(member)
                done.append(f"added {member.name} ({member.age_group})" + (f" who avoids {label(rid).lower()}" if rid else ""))
            elif op["op"] == "add_restriction":
                member = next((m for m in household.members if m.name.lower() == op["member"].lower()), None)
                if member is None or rid is None:
                    refused.append(f"I couldn't find {op['member']} in your household." if member is None else "Which restriction?")
                    continue
                if any(p.restriction == rid for p in member.dietary_profiles):
                    refused.append(f"{member.name} already avoids {label(rid).lower()}.")
                    continue
                member.dietary_profiles.append(DietaryProfile(restriction=rid, kind=kind, severity=severity))
                done.append(f"{member.name} now avoids {label(rid).lower()} ({severity})")
        if done:
            self.db.flush()
            self.ctx.manager.log("update_profile", "From chat: " + "; ".join(done), session_id=s.id)
        if not done and not refused:
            return result.data.get("clarification_question") or "What should I change in your household?"
        reply = ("Saved to your household: " + "; ".join(done) + "." if done else "") + (" " + " ".join(refused) if refused else "")
        if done and has_basket:
            reply += " Your current basket was built before this change, so start a new shop to apply it."
        return reply.strip()


def _remember(s: ShoppingSession, role: str, text: str) -> None:
    s.chat_history = list(s.chat_history or []) + [{"role": role, "text": text, "at": datetime.now().isoformat(timespec="seconds")}]


def _intake_reply(req: ShoppingRequest) -> str:
    if req.pending_questions:
        return " ".join(q["question"] for q in req.pending_questions)
    if req.mode == "form" and req.stage == "awaiting_form":
        return "Let's do this one field by field — please check the form."
    return "Here's what I understood. Check it and confirm, or tell me what to change."
