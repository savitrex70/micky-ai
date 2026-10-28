"""API and persistence tests for user-controlled memory."""
from collections.abc import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import rop.models  # noqa: F401
from rop.database import Base, get_db
from rop.main import app

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"origin": ORIGIN, "content-type": "application/json"}

def pytest_client_fixture():
    return None

