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
                response["reply"] = "Done — " + ", ".join(result["applied"]) + "." + (
                    " " + " ".join(result["conflicts"]) if result.get("conflicts") else "")
            else:
                response["reply"] = result.get("question") or result.get("message")
        elif intent == "explain":
            explanation = self.ctx.manager.explain_for(basket)
            response.update(kind="explain", reply=explanation["text"])
        elif intent == "meal_plan":
            plan = self.plan_meals(basket)
            response.update(kind="meal_plan", meal_plan_id=plan.id, reply=plan.summary)
        elif intent == "compare_prices":
            report = self.ctx.analyst.compare(basket)
            response.update(kind="compare", reply=report["insight"] or "I couldn't price enough items to compare stores.")
        else:
            reply = self.think("chat_reply", {"text": text, "state": state})
            response.update(kind="chat", reply=reply.data)

        _remember(s, "assistant", response["reply"])
        return response


def _remember(s: ShoppingSession, role: str, text: str) -> None:
    s.chat_history = list(s.chat_history or []) + [{"role": role, "text": text, "at": datetime.now().isoformat(timespec="seconds")}]


def _intake_reply(req: ShoppingRequest) -> str:
    if req.pending_questions:
        return " ".join(q["question"] for q in req.pending_questions)
    if req.mode == "form" and req.stage == "awaiting_form":
        return "Let's do this one field by field — please check the form."
    return "Here's what I understood. Check it and confirm, or tell me what to change."
