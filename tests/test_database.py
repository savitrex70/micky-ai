import rop.database as database


def test_engine_uses_configured_postgresql_driver() -> None:
    assert database.engine.url.drivername == "postgresql+psycopg"


def test_base_registers_reasoning_session_model() -> None:
    assert "reasoning_sessions" in database.Base.metadata.tables


def test_database_dependency_closes_session(monkeypatch) -> None:
    class TrackingSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    session = TrackingSession()
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    dependency = database.get_db()
    assert next(dependency) is session
    dependency.close()

    assert session.closed
