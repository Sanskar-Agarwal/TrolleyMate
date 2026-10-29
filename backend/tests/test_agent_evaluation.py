"""KAN-23: the safety regression gate. Runs the fixed evaluation set in tests/agent_evaluation.py
(perception, tool-based decisions and system actions, with unsafe and uncertain inputs and failed
tools). docs/evidence/agent-evaluation.md records the observed results and the limitations."""

import pytest

from tests.agent_evaluation import CAPABILITIES, EVAL_SET, EVAL_SET_VERSION, INPUTS, LIMITATIONS, run

# Uncertain items stay withheld until an authorised reviewer decides (acceptance criterion 3).
WITHHELD_UNTIL_REVIEW = {
    "T10-provider-down-without-fallback", "S02-uncertain-item-withheld-and-escalated", "S03-withheld-item-blocks-acceptance",
    "S04-only-an-authorised-reviewer-decides", "S05-review-decision-applied-and-audited", "S06-rebuild-keeps-the-item-withheld",
    "S07-chat-edit-cannot-release-a-withheld-extra", "S10-swap-rechecked-at-accept", "S15-basket-built-during-an-outage",
}


def test_the_evaluation_set_is_fixed_and_covers_every_capability_and_input():
    ids = [c.id for c in EVAL_SET]
    assert EVAL_SET_VERSION and len(ids) == len(set(ids)) == 42
    assert {c.capability for c in EVAL_SET} == set(CAPABILITIES)
    for capability in CAPABILITIES:
        assert {c.input for c in EVAL_SET if c.capability == capability} == set(INPUTS), capability
    assert {c.input for c in EVAL_SET} == set(INPUTS)
    assert sum(c.input == "failed_tool" for c in EVAL_SET) >= 5
    assert sum(c.input == "uncertain" for c in EVAL_SET) >= 5
    assert all(c.trace and c.expected for c in EVAL_SET)
    assert WITHHELD_UNTIL_REVIEW <= set(ids)
    assert LIMITATIONS


@pytest.mark.parametrize("case", EVAL_SET, ids=lambda c: c.id)
def test_case(case):
    observation = run(case)
    assert observation.passed, observation.observed
