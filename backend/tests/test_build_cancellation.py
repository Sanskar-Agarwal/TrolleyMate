"""UC-02: real concurrent cancel requests must win before the transaction commits."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain import Basket, ConstraintSetRecord
from app.services.build_control import BuildCancelled, BuildConflict, BuildRegistry
from tests.test_basket_flow import confirmed_session


def _accepted(client, headers):
    sid = confirmed_session(client, headers, "$100 for 3 days, dinner only for myself")
    basket = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=headers).json()["basket"]
    assert client.post(f"/api/baskets/{basket['id']}/accept", headers=headers).status_code == 200
    return sid, basket


@pytest.mark.parametrize("route,body", [("basket", {"goal": "balanced"}), ("negotiate", {"budget": 120, "days": 2})])
def test_cancel_after_candidate_creation_rolls_back_basket_and_override(client, riley, monkeypatch, route, body):
    from app.agents.technical_manager import TechnicalManagerAgent

    sid, old = _accepted(client, riley)
    before = client.get(f"/api/sessions/{sid}", headers=riley).json()
    ready, release = Event(), Event()
    original = TechnicalManagerAgent.explain_for

    def pause_after_candidate_saved(self, basket):
        assert basket.id != old["id"]
        ready.set()
        assert release.wait(10), "Concurrent cancellation request did not finish"
        return original(self, basket)

    monkeypatch.setattr(TechnicalManagerAgent, "explain_for", pause_after_candidate_saved)
    operation_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f"/api/sessions/{sid}/{route}", json={**body, "operation_id": operation_id}, headers=riley)
        try:
            assert ready.wait(10), "Build did not reach the presentation checkpoint"
            cancel = client.post(f"/api/sessions/{sid}/basket-builds/{operation_id}/cancel", headers=riley)
            assert cancel.status_code == 200, cancel.text
            assert cancel.json()["status"] == "cancellation_requested"
            duplicate = client.post(f"/api/sessions/{sid}/basket", json={"operation_id": str(uuid4())}, headers=riley)
            assert duplicate.status_code == 409
        finally:
            release.set()
        response = future.result(timeout=15)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert response.json()["trace"] == []  # rolled-back candidate decisions must not appear as committed evidence
    after = client.get(f"/api/sessions/{sid}", headers=riley).json()
    assert after["basket"]["id"] == old["id"] and after["basket"]["status"] == "accepted"
    assert after["basket"]["total"] == old["total"]
    assert after["constraints"] == before["constraints"]
    assert after["session"] == before["session"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Basket).where(Basket.session_id == sid)) == 1
        assert db.scalar(select(func.count()).select_from(ConstraintSetRecord).where(ConstraintSetRecord.session_id == sid)) == 1
    assert client.post(f"/api/sessions/{sid}/basket-builds/{operation_id}/cancel", headers=riley).json() == {
        "status": "already_finished", "outcome": "cancelled", "trace": []}


def test_cancellation_before_build_arrives_prevents_any_candidate(client, riley, monkeypatch):
    from app.optimisation import BasketOptimiser

    sid, old = _accepted(client, riley)
    operation_id = str(uuid4())
    response = client.post(f"/api/sessions/{sid}/basket-builds/{operation_id}/cancel", headers=riley)
    assert response.json()["status"] == "cancellation_requested"

    def must_not_solve(*args, **kwargs):
        pytest.fail("Pre-cancelled request reached the solver")

    monkeypatch.setattr(BasketOptimiser, "solve", must_not_solve)
    response = client.post(f"/api/sessions/{sid}/basket", json={"operation_id": operation_id}, headers=riley)
    assert response.json()["status"] == "cancelled"
    assert client.get(f"/api/sessions/{sid}", headers=riley).json()["basket"]["id"] == old["id"]


def test_cancel_after_commit_reports_finished_and_does_not_undo_basket(client, riley):
    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    operation_id = str(uuid4())
    built = client.post(f"/api/sessions/{sid}/basket", json={"operation_id": operation_id}, headers=riley)
    assert built.json()["status"] == "ok"
    response = client.post(f"/api/sessions/{sid}/basket-builds/{operation_id}/cancel", headers=riley)
    assert response.json() == {"status": "already_finished", "outcome": "committed", "trace": []}
    assert client.get(f"/api/sessions/{sid}", headers=riley).json()["basket"]["id"] == built.json()["basket"]["id"]
    assert client.post(f"/api/sessions/{sid}/basket", json={"operation_id": operation_id}, headers=riley).status_code == 409


def test_other_shopper_cannot_cancel_or_reserve_an_operation(client, riley, alex):
    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    operation_id = str(uuid4())
    assert client.post(f"/api/sessions/{sid}/basket-builds/{operation_id}/cancel", headers=alex).status_code == 404
    assert client.post(f"/api/sessions/{sid}/basket-builds/{operation_id}/cancel").status_code == 401
    assert client.post(f"/api/sessions/{sid}/basket", json={"operation_id": operation_id}, headers=riley).json()["status"] == "ok"


def test_commit_gate_resolves_cancel_race_without_false_cancel_success():
    registry = BuildRegistry()
    saving, finish_save, cancel_started = Event(), Event(), Event()

    def build():
        with registry.track(1, "operation") as operation:
            def save():
                saving.set()
                assert finish_save.wait(5)
            registry.commit(operation, save)

    def cancel():
        cancel_started.set()
        return registry.cancel(1, "operation")

    with ThreadPoolExecutor(max_workers=2) as pool:
        built = pool.submit(build)
        assert saving.wait(5)
        cancelled = pool.submit(cancel)
        try:
            assert cancel_started.wait(5)
        finally:
            finish_save.set()
        built.result(timeout=5)
        assert cancelled.result(timeout=5) == {"status": "already_finished", "outcome": "committed"}


def test_registry_is_bounded_and_expired_tombstones_are_cleaned(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.services.build_control.time.monotonic", lambda: clock[0])
    registry = BuildRegistry(retention_seconds=10, max_entries=2)
    registry.cancel(1, "one")
    registry.cancel(2, "two")
    with pytest.raises(BuildConflict, match="Too many"):
        registry.cancel(3, "three")
    clock[0] = 111
    # Active work is retained beyond TTL and sessions can run independently.
    with pytest.raises(BuildCancelled):
        with registry.track(1, "new") as operation:
            clock[0] = 122
            with pytest.raises(BuildConflict, match="already running"):
                with registry.track(1, "duplicate"):
                    pass
            with registry.track(2, "independent") as other:
                registry.commit(other, lambda: None)
            registry.cancel(1, "new")
            registry.commit(operation, lambda: pytest.fail("Cancelled operation committed"))
