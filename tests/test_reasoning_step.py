from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base
from rop.models import ReasoningStep
from rop.models.reasoning_step import StepType
from rop.schemas import ReasoningSessionCreate, ReasoningStepCreate
from rop.services import ReasoningSessionService, ReasoningStepService

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def test_reasoning_step_crud_and_ordering() -> None:
    session_service = ReasoningSessionService()
    step_service = ReasoningStepService()

    with TestingSessionLocal() as db:
        session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )

        step1 = step_service.create(
            db,
            ReasoningStepCreate(
                session_id=session.id,
                step_type=StepType.INPUT,
                input_data={"text": "input"},
                output_data={"text": "output"},
                confidence=0.9,
                duration_ms=100,
                status="completed",
            ),
        )
        step2 = step_service.create(
            db,
            ReasoningStepCreate(
                session_id=session.id,
                step_type=StepType.OBSERVATION_EXTRACTION,
                input_data={"text": "input"},
                output_data={"observations": []},
                confidence=0.8,
                duration_ms=200,
                status="completed",
            ),
        )

        assert step1.step_number == 1
        assert step2.step_number == 2
        assert step_service.get(db, step1.id) is step1
        assert step_service.get(db, step2.id) is step2
        steps = step_service.list_by_session(db, session.id)
        assert [s.step_number for s in steps] == [1, 2]
        assert steps == [step1, step2]


def test_replay_returns_steps_in_order() -> None:
    session_service = ReasoningSessionService()
    step_service = ReasoningStepService()

    with TestingSessionLocal() as db:
        session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )

        for step_type in [
            StepType.INPUT,
            StepType.HYPOTHESIS,
            StepType.EVIDENCE,
        ]:
            step_service.create(
                db,
                ReasoningStepCreate(
                    session_id=session.id,
                    step_type=step_type,
                    input_data={},
                    output_data={},
                    confidence=0.5,
                    duration_ms=50,
                    status="completed",
                ),
            )

        replay = step_service.replay(db, session.id)
        assert [step.step_type for step in replay] == [
            StepType.INPUT,
            StepType.HYPOTHESIS,
            StepType.EVIDENCE,
        ]


def test_step_number_continues_across_sessions() -> None:
    session_service = ReasoningSessionService()
    step_service = ReasoningStepService()

    with TestingSessionLocal() as db:
        session1 = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )
        session2 = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )

        step_service.create(
            db,
            ReasoningStepCreate(
                session_id=session1.id,
                step_type=StepType.INPUT,
                input_data={},
                output_data={},
                confidence=0.5,
                duration_ms=50,
                status="completed",
            ),
        )
        step_service.create(
            db,
            ReasoningStepCreate(
                session_id=session2.id,
                step_type=StepType.INPUT,
                input_data={},
                output_data={},
                confidence=0.5,
                duration_ms=50,
                status="completed",
            ),
        )

        steps1 = step_service.list_by_session(db, session1.id)
        steps2 = step_service.list_by_session(db, session2.id)
        assert steps1[0].step_number == 1
        assert steps2[0].step_number == 1


def test_reasoning_step_table_has_required_columns() -> None:
    columns = {column.name for column in ReasoningStep.__table__.columns}

    assert columns == {
        "id",
        "session_id",
        "step_number",
        "step_type",
        "input_data",
        "output_data",
        "confidence",
        "duration_ms",
        "status",
        "created_at",
    }
