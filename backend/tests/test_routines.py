import uuid
from datetime import UTC, date, datetime, time

import pytest
from pydantic import ValidationError

from app.api.routes.routines import router
from app.models import (
    FoodItem,
    MealLog,
    MealLogMutation,
    MealOccurrence,
    MealOccurrenceLog,
    MealRoutine,
    MealSchedule,
    PlanningMutation,
)
from app.schemas.routines import (
    OccurrenceComplete,
    OccurrenceSkip,
    RoutineWrite,
    ScheduleCreate,
    ScheduleStateChange,
)
from app.services.routines import (
    RoutineError,
    _owned_routine,
    _replay,
    _validated_products,
    change_schedule_state,
    complete_occurrence,
    mutation_fingerprint,
    skip_occurrence,
)


class GetSession:
    def __init__(self, value):
        self.value = value
        self.keys = []

    async def get(self, _model, key):
        self.keys.append(key)
        return self.value


class Result:
    def __init__(self, rows=None, scalar=None):
        self.rows = rows or []
        self.scalar = scalar

    def all(self):
        return self.rows

    def scalars(self):
        return self

    def first(self):
        return self.scalar


class LifecycleSession:
    def __init__(self, results):
        self.results = iter(results)
        self.added = []

    async def execute(self, _statement):
        return next(self.results)

    def add(self, value):
        self.added.append(value)


class ExecuteSession:
    def __init__(self, result):
        self.result = result

    async def execute(self, _statement):
        return self.result


class RowCountResult(Result):
    rowcount = 1


class ScheduleStateSession:
    def __init__(self, schedule):
        self.schedule = schedule
        self.statements = []

    async def get(self, _model, _key):
        return self.schedule

    async def execute(self, statement):
        self.statements.append(statement)
        return RowCountResult()


def rough_request(**overrides) -> RoutineWrite:
    values = {
        "client_mutation_id": uuid.uuid4(),
        "title": "Workday breakfast",
        "mode": "rough",
        "rough_text": "Yogurt, fruit, and something crunchy",
    }
    values.update(overrides)
    return RoutineWrite(**values)


def test_routine_contract_keeps_rough_and_defined_modes_separate():
    rough = rough_request()
    assert rough.items == []
    with pytest.raises(ValidationError, match="rough routines require"):
        rough_request(items=[{"food_item_id": uuid.uuid4(), "quantity_g": 100}])
    with pytest.raises(ValidationError, match="defined routines require"):
        rough_request(mode="defined", rough_text=None, items=[])


def test_schedule_contract_enforces_bounded_recurrence_shape():
    common = {
        "client_mutation_id": uuid.uuid4(),
        "local_time": time(8),
        "timezone": "Europe/Lisbon",
        "start_date": date(2026, 9, 2),
    }
    with pytest.raises(ValidationError):
        ScheduleCreate(**common, frequency="daily", interval=5)
    with pytest.raises(ValidationError, match="weekly schedules require weekdays"):
        ScheduleCreate(**common, frequency="weekly")


def test_mutation_fingerprint_ignores_idempotency_key_but_covers_payload():
    first = rough_request(client_mutation_id=uuid.uuid4())
    replay = rough_request(client_mutation_id=uuid.uuid4())
    changed = rough_request(client_mutation_id=uuid.uuid4(), title="Weekend breakfast")
    assert mutation_fingerprint(first) == mutation_fingerprint(replay)
    assert mutation_fingerprint(first) != mutation_fingerprint(changed)


@pytest.mark.asyncio
async def test_planning_replay_is_user_scoped_and_rejects_key_reuse():
    user_id = uuid.uuid4()
    mutation_id = uuid.uuid4()
    mutation = PlanningMutation(
        user_id=user_id,
        client_mutation_id=mutation_id,
        operation="routine_create",
        request_fingerprint="same",
        resource_id=uuid.uuid4(),
    )
    session = GetSession(mutation)
    assert await _replay(
        session, user_id, mutation_id, "routine_create", "same"  # type: ignore[arg-type]
    ) is mutation
    assert session.keys == [{"user_id": user_id, "client_mutation_id": mutation_id}]

    with pytest.raises(RoutineError, match="different operation or payload") as exc:
        await _replay(
            session, user_id, mutation_id, "occurrence_skip", "same"  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_owned_routine_hides_other_users_and_archived_rows():
    owner_id = uuid.uuid4()
    routine = MealRoutine(id=uuid.uuid4(), user_id=owner_id, archived_at=None)
    assert await _owned_routine(
        GetSession(routine), owner_id, routine.id, active=True  # type: ignore[arg-type]
    ) is routine

    with pytest.raises(RoutineError) as other_user:
        await _owned_routine(
            GetSession(routine), uuid.uuid4(), routine.id  # type: ignore[arg-type]
        )
    assert other_user.value.status_code == 404


@pytest.mark.asyncio
async def test_defined_routine_products_must_be_accepted_and_not_archived():
    product_id = uuid.uuid4()
    product = FoodItem(id=product_id, archived_at=None)
    accepted = await _validated_products(
        ExecuteSession(Result(rows=[product])),  # type: ignore[arg-type]
        [product_id],
    )
    assert accepted == {product_id: product}

    with pytest.raises(RoutineError, match="accepted, non-archived") as exc:
        await _validated_products(
            ExecuteSession(Result(rows=[])),  # type: ignore[arg-type]
            [product_id],
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_complete_resolves_meal_mutations_and_links_without_writing_meals(monkeypatch):
    user_id = uuid.uuid4()
    occurrence = MealOccurrence(id=uuid.uuid4(), status="scheduled")
    mutation_ids = [uuid.uuid4(), uuid.uuid4()]
    logs = [MealLog(id=uuid.uuid4(), user_id=user_id), MealLog(id=uuid.uuid4(), user_id=user_id)]
    mutations = [
        MealLogMutation(
            user_id=user_id,
            client_mutation_id=mutation_id,
            request_fingerprint="meal",
            meal_log_id=log.id,
        )
        for mutation_id, log in zip(mutation_ids, logs)
    ]
    session = LifecycleSession(
        [Result(rows=list(zip(mutations, logs))), Result(scalar=None), Result()]
    )
    commits = []

    async def no_replay(*_args):
        return None

    async def owned(*_args):
        return occurrence

    async def commit(*_args, **kwargs):
        commits.append(kwargs)
        return occurrence.id

    async def output(*_args):
        return occurrence

    monkeypatch.setattr("app.services.routines._replay", no_replay)
    monkeypatch.setattr("app.services.routines._owned_occurrence", owned)
    monkeypatch.setattr("app.services.routines._commit_mutation", commit)
    monkeypatch.setattr("app.services.routines._occurrence_out", output)

    result = await complete_occurrence(
        session,  # type: ignore[arg-type]
        user_id,
        occurrence.id,
        OccurrenceComplete(
            client_mutation_id=uuid.uuid4(),
            confirmed_at=datetime(2026, 9, 2, 12, tzinfo=UTC),
            meal_log_client_mutation_ids=mutation_ids,
        ),
    )
    links = [item for item in session.added if isinstance(item, MealOccurrenceLog)]
    assert result is occurrence
    assert occurrence.status == "completed"
    assert [link.meal_log_id for link in links] == [log.id for log in logs]
    assert all(link.user_id == user_id for link in links)
    assert not any(isinstance(item, MealLog) for item in session.added)
    assert commits[0]["operation"] == "occurrence_complete"


@pytest.mark.asyncio
async def test_skip_changes_lifecycle_and_records_idempotent_operation(monkeypatch):
    user_id = uuid.uuid4()
    occurrence = MealOccurrence(id=uuid.uuid4(), status="scheduled")
    session = LifecycleSession([Result()])
    commits = []

    async def no_replay(*_args):
        return None

    async def owned(*_args):
        return occurrence

    async def commit(*_args, **kwargs):
        commits.append(kwargs)
        return occurrence.id

    async def output(*_args):
        return occurrence

    monkeypatch.setattr("app.services.routines._replay", no_replay)
    monkeypatch.setattr("app.services.routines._owned_occurrence", owned)
    monkeypatch.setattr("app.services.routines._commit_mutation", commit)
    monkeypatch.setattr("app.services.routines._occurrence_out", output)

    result = await skip_occurrence(
        session,  # type: ignore[arg-type]
        user_id,
        occurrence.id,
        OccurrenceSkip(
            client_mutation_id=uuid.uuid4(),
            acted_at=datetime(2026, 9, 2, 12, tzinfo=UTC),
        ),
    )
    assert result is occurrence
    assert occurrence.status == "skipped"
    assert occurrence.acted_at == datetime(2026, 9, 2, 12, tzinfo=UTC)
    assert commits[0]["operation"] == "occurrence_skip"


@pytest.mark.asyncio
async def test_schedule_reenable_only_uncancels_live_scheduled_occurrence_intents(monkeypatch):
    user_id = uuid.uuid4()
    schedule = MealSchedule(id=uuid.uuid4(), user_id=user_id, routine_id=uuid.uuid4(), version=2)
    session = ScheduleStateSession(schedule)

    async def no_replay(*_args):
        return None

    async def commit(*_args, **_kwargs):
        return schedule.id

    async def output(_session, value):
        return value

    monkeypatch.setattr("app.services.routines._replay", no_replay)
    monkeypatch.setattr("app.services.routines._commit_mutation", commit)
    monkeypatch.setattr("app.services.routines._schedule_out", output)
    await change_schedule_state(
        session,  # type: ignore[arg-type]
        user_id,
        schedule.id,
        ScheduleStateChange(
            client_mutation_id=uuid.uuid4(), expected_version=2, enabled=True
        ),
    )
    sql = str(session.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "meal_occurrences.status = 'scheduled'" in sql
    assert "notification_intents.expires_at >" in sql
    assert "notification_intents.scheduled_for >" in sql


def test_route_surface_is_explicit_and_contains_no_meal_write():
    surface = {(route.path, next(iter(route.methods))) for route in router.routes}
    assert surface == {
        ("/api/routines", "GET"),
        ("/api/routines", "POST"),
        ("/api/routines/{routine_id}", "GET"),
        ("/api/routines/{routine_id}", "PUT"),
        ("/api/routines/{routine_id}/archive", "POST"),
        ("/api/routines/{routine_id}/schedules", "GET"),
        ("/api/routines/{routine_id}/schedules", "POST"),
        ("/api/schedules/{schedule_id}", "PATCH"),
        ("/api/agenda/refresh", "POST"),
        ("/api/occurrences/{occurrence_id}/complete", "POST"),
        ("/api/occurrences/{occurrence_id}/skip", "POST"),
    }
    assert all("meal-logs" not in path for path, _method in surface)
