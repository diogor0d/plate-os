"""Lock the recovery guards to the migration set (postmortem: 0003 shipped
without extending the backup/restore revision allowlists)."""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _migration_revisions() -> list[str]:
    revisions = []
    for path in sorted((BACKEND / "alembic" / "versions").glob("*.py")):
        match = re.search(r'^revision:\s*str\s*=\s*"(\d+)"', path.read_text(encoding="utf-8"), re.M)
        assert match, f"No revision id found in {path.name}"
        revisions.append(match.group(1))
    return revisions


def _allowed_revisions(script_text: str) -> set[str]:
    allowed: set[str] = set()
    for choices in re.findall(r"(\d+(?:\|\d+)*)\)\s*;;", script_text):
        allowed.update(choices.split("|"))
    return allowed


def test_recovery_guards_accept_every_migration():
    revisions = _migration_revisions()
    assert revisions, "No migrations discovered"
    for script in ("backup.sh", "restore.sh"):
        text = (REPO / "ops" / "backup" / script).read_text(encoding="utf-8")
        allowed = _allowed_revisions(text)
        missing = [rev for rev in revisions if rev not in allowed]
        assert not missing, f"{script} does not accept schema revisions {missing}"


def test_guard_cases_stay_ordered_with_history():
    revisions = _migration_revisions()
    text = (REPO / "ops" / "backup" / "backup.sh").read_text(encoding="utf-8")
    positions = [
        match.start()
        for match in re.finditer(r"\d+(?:\|\d+)*\)\s*;;", text)
        if _allowed_revisions(match.group(0))
    ]
    assert positions == sorted(positions), "Revision cases drifted out of history order"
