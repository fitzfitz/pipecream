import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Isolated SQLite DB + artifact dir for each test. Returns the data dir."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DB_PATH", str(data_dir / "factory.db"))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    import db
    db.init_db()
    return data_dir
