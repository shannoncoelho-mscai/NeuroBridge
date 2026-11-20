from datetime import datetime, timedelta
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# Never let tests pick up real keys or auto-initialise from the environment.
for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"):
    os.environ.pop(key, None)
os.environ["NEUROBRIDGE_AUTO_INIT"] = "0"
import tempfile  # noqa: E402
os.environ.setdefault("NEUROBRIDGE_APP_DB", str(Path(tempfile.mkdtemp()) / "app.sqlite3"))
os.environ.pop("NEUROBRIDGE_DISABLE_LEGACY_API", None)


@pytest.fixture(autouse=True)
def isolated_dbs(tmp_path, monkeypatch):
    import agent.memory.memory_store as ms
    monkeypatch.setattr(ms, "MEMORY_DB", tmp_path / "memory.sqlite3")
    ms.initialize_memory()
    yield tmp_path


@pytest.fixture
def store(tmp_path):
    from agent.tools.booking_db import BookingStore
    return BookingStore(tmp_path / "bookings.sqlite3")


@pytest.fixture
def verified_provider(store):
    p = store.register_provider("Test Child Psychology Practice", "Clinical Psychologist",
                                specialties=["child psychology"], age_groups=["children 3-12"],
                                languages=["English", "Konkani"], location="Panjim, Goa")
    store.verify_provider(p["provider_id"])
    day = (datetime.now() + timedelta(days=10)).date().isoformat()   # always in the future
    slot = store.add_availability(p["provider_id"], f"{day}T10:00:00",
                                  f"{day}T11:00:00", fee_amount=1200)
    return {"provider_id": p["provider_id"], "slot_id": slot["slot_id"]}


def make_agent(search=None, reader=None, store=None, **overrides):
    from fakes import make_gateway, FakeSearch, FakeReader
    from agent.tools.builtin import build_tool_registry
    from agent.skills import load_default_skills
    from agent.orchestrator import NeuroBridgeAgent
    gw, llm = make_gateway(**overrides)
    search = search or FakeSearch()
    reader = reader or FakeReader()
    reg = build_tool_registry(booking_store=store, search_fn=search, reader_fn=reader)
    agent = NeuroBridgeAgent(gw, reg, load_default_skills(), retry_backoff=0)
    return agent, llm, search, reader
