"""Compliance verdict contract (1.2.10, 1.2.11 interfaces) — what NutritionComplianceAgent hands
to the other agents. Owner: Compliance & Preferences.

Traces to Stage 1 sequence 8.4 and state machine 9.4:

  Product level — 8.4 classifyProduct(): compliant | violation | uncertain  (ItemCompliance)
  Basket level  — 9.4 final states, stored as VerdictStatus:
      Passed                                         → passed     (outcome PASS)
      Failed                                         → failed     (outcome FAIL)
      Uncertain [still unresolved] → EscalationRequested → escalated  (outcome ESCALATED)

A violation outranks uncertainty (7.4 "Overall result? [any violation]"), so a basket holding
both fails. Uncertain products are withheld and never inserted automatically (UC-06 ext 2a).
What happens after escalation is the human-review extension (9.5), outside this contract.

`VerdictEvidence` is the shape stored in ComplianceVerdict.evidence. `verify()` validates against
it, so a change to the shape breaks a test instead of a consumer.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ItemCompliance, VerdictStatus

SCHEMA_VERSION = 1

ProductStatus = Literal["compliant", "violation", "uncertain"]

# contains     — an ingredient or sub-ingredient carries a restricted tag
# ambiguous    — a vague label term the LLM judged likely/possible to hide the restriction
# may_contain  — a precautionary "may contain" statement on the label
# missing_data — the ingredient evidence is absent (no list, or an empty one)
# data_error   — the evidence exists but can't be trusted (corrupt or cyclic) — UC-06 failure scenario
# human_review — a dietitian's earlier decision on this product for this household
FindingKind = Literal["contains", "ambiguous", "may_contain", "missing_data", "data_error", "human_review"]


class _Contract(BaseModel):
    # Unknown keys are an error, not silently dropped: new evidence must be added here first.
    model_config = ConfigDict(extra="forbid")


class Evidence(_Contract):
    """One reason behind a product's status (8.4 recordFindings)."""

    kind: FindingKind
    detail: str
    restriction: str | None = None
    ingredient: str | None = None  # cascade path, e.g. "basil pesto → pine nuts"


class ProductResult(_Contract):
    product_id: int
    product: str
    status: ProductStatus
    confidence: float = Field(ge=0, le=1)
    findings: list[Evidence] = []

    @model_validator(mode="after")
    def _explained(self) -> ProductResult:
        if self.status != ItemCompliance.compliant and not self.findings:
            raise ValueError(f"a {self.status} product needs at least one finding to explain it")
        return self


class AppliedRestriction(_Contract):
    restriction: str
    severity: str  # Severity value; kept as given so an unexpected intake value can't crash verification
    label: str


class NutrientCoverage(_Contract):
    nutrient: str
    required: float
    provided: float
    coverage_pct: int
    met: bool


class NutrientGap(_Contract):
    nutrient: str
    required: float
    provided: float
    short_by: float


class NutritionCoverage(_Contract):
    """1.2.11 — what the basket's non-withheld items provide against the targets."""

    adequate: bool
    provided: dict[str, float]
    required: dict[str, float]
    coverage: list[NutrientCoverage]
    gaps: list[NutrientGap]
    suggestions: list[str]
    targets: str  # nutrition_targets.TARGETS_VERSION the requirements were built from

    @model_validator(mode="after")
    def _consistent(self) -> NutritionCoverage:
        unmet = {c.nutrient for c in self.coverage if not c.met}
        if unmet != {g.nutrient for g in self.gaps}:
            raise ValueError("gaps must list exactly the nutrients whose coverage is not met")
        if self.adequate != (not unmet):
            raise ValueError("adequate must be true only when every target is met")
        return self


class VerdictEvidence(_Contract):
    schema_version: int = SCHEMA_VERSION
    restrictions: list[AppliedRestriction]
    products: list[ProductResult]
    nutrition: NutritionCoverage | None = None


def outcome(statuses: Iterable[str]) -> VerdictStatus:
    """9.4 — consolidate product results into the basket verdict."""
    found = set(statuses)
    if ItemCompliance.violation in found:
        return VerdictStatus.failed
    if ItemCompliance.uncertain in found:
        return VerdictStatus.escalated
    return VerdictStatus.passed
