"""KAN-24: the contribution statement in docs/CONTRIBUTIONS.md. Each criterion's shares must total
100% before they go on the supplied form, and student IDs never enter the repository."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "contributions.py"
_spec = importlib.util.spec_from_file_location("contributions", SCRIPT)
contributions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contributions)

MEMBERS = list(contributions.MEMBERS)


def table(rows: dict[str, str]) -> str:
    lines = ["## Agreed percentages", "", "| Member | C1 | C2 | C3 | C4 |", "|---|---|---|---|---|"]
    lines += [f"| {m} | {cells} |" for m, cells in rows.items()]
    return "\n".join([*lines, "| **Total** | | | | |", "", "## Next section", "| a | b | c | d | e |"]) + "\n"


AGREED = {m: "20% | 20 | 20 | 20" for m in MEMBERS}


def test_the_committed_statement_is_blank_or_every_criterion_totals_100():
    shares = contributions.read_shares(contributions.DOC.read_text(encoding="utf-8"))
    assert set(shares) == set(MEMBERS)  # one row per member, in the table the form is filled from
    assert contributions.pending(shares) or contributions.problems(shares) == []


def test_a_criterion_that_does_not_total_100_is_caught():
    shares = contributions.read_shares(table({**AGREED, MEMBERS[0]: "20 | 15 | 20 | 20"}))
    assert contributions.problems(shares) == ["C2 AI agents: totals 95%, not 100%"]


def test_a_missing_member_a_blank_share_or_a_stranger_is_caught():
    rows = {m: v for m, v in AGREED.items() if m != MEMBERS[1]} | {MEMBERS[2]: "20 | 20 |  | 20", "Someone Else": "20 | 20 | 20 | 20"}
    found = contributions.problems(contributions.read_shares(table(rows)))
    assert f"{MEMBERS[1]} has no row" in found and "'Someone Else' isn't a team member" in found
    assert f"C3 Agile: no share agreed for {MEMBERS[2]}" in found


def test_a_share_that_is_not_a_number_is_reported():
    with pytest.raises(ValueError, match="isn't a percentage"):
        contributions.read_shares(table({**AGREED, MEMBERS[0]: "20 | TBD | 20 | 20"}))


def test_the_form_ready_table_needs_every_student_id_and_is_written_outside_the_repo(tmp_path, monkeypatch, capsys):
    doc = tmp_path / "CONTRIBUTIONS.md"
    doc.write_text(table(AGREED), encoding="utf-8")
    monkeypatch.setattr(contributions, "DOC", doc)
    ids = tmp_path / "ids.csv"
    ids.write_text("Member,Student ID\n" + "".join(f"{m},5000000{i}\n" for i, m in enumerate(MEMBERS[:-1])), encoding="utf-8")
    out = tmp_path / "statement.md"

    assert contributions.main(["check", "--ids", str(ids), "--out", str(out)]) == 1
    assert f"{MEMBERS[-1]} has no student ID" in capsys.readouterr().out and not out.exists()

    ids.write_text(ids.read_text(encoding="utf-8") + f"{MEMBERS[-1]},500000099\n", encoding="utf-8")
    inside = contributions.REPO / "docs" / "statement.md"
    assert contributions.main(["check", "--ids", str(ids), "--out", str(inside)]) == 1
    assert "outside the repository" in capsys.readouterr().out and not inside.exists()

    assert contributions.main(["check", "--ids", str(ids), "--out", str(out)]) == 0
    written = out.read_text(encoding="utf-8")
    assert "500000099" in written and written.count("**100%**") == 4


def test_refreshing_the_evidence_keeps_everything_the_team_wrote():
    text = "intro\n<!-- evidence:start -->\nold\n<!-- evidence:end -->\nthe team's notes\n"
    assert contributions.replace_evidence(text, "new") == "intro\n<!-- evidence:start -->\nnew\n<!-- evidence:end -->\nthe team's notes\n"
