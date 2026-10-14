"""AgentContext — one per HTTP request. Holds the DB session, LLM service, acting
user, the four agents, and a `trace` of every decision made during the request
(returned to the UI so the shopper can watch the agents work)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.llm import LLMService

if TYPE_CHECKING:
    from app.agents.market_analyst import MarketAnalystAgent
    from app.agents.nutrition_compliance import NutritionComplianceAgent
    from app.agents.personal_shopper import PersonalShopperAgent
    from app.agents.technical_manager import TechnicalManagerAgent
    from app.domain import User


@dataclass
class AgentContext:
    db: Session
    llm: LLMService
    user: User | None = None
    trace: list[dict] = field(default_factory=list)

    @cached_property
    def shopper(self) -> PersonalShopperAgent:
        from app.agents.personal_shopper import PersonalShopperAgent

        return PersonalShopperAgent(self)

    @cached_property
    def analyst(self) -> MarketAnalystAgent:
        from app.agents.market_analyst import MarketAnalystAgent

        return MarketAnalystAgent(self)

    @cached_property
    def compliance(self) -> NutritionComplianceAgent:
        from app.agents.nutrition_compliance import NutritionComplianceAgent

        return NutritionComplianceAgent(self)

    @cached_property
    def manager(self) -> TechnicalManagerAgent:
        from app.agents.technical_manager import TechnicalManagerAgent

        return TechnicalManagerAgent(self)
