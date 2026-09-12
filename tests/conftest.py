import os

os.environ.setdefault("ROP_APP_NAME", "Reasoning Operating Platform")
os.environ.setdefault("ROP_ENVIRONMENT", "testing")
os.environ.setdefault("ROP_LOG_LEVEL", "INFO")
os.environ.setdefault(
    "ROP_DATABASE_URL", "postgresql+psycopg://rop:rop@localhost:5432/rop"
)
