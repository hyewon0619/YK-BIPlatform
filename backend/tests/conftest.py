import os
import sys
import tempfile
from pathlib import Path

# db 모듈은 import 시점에 경로를 정하므로, 테스트용 DB 경로를 먼저 지정한다.
_DB = Path(tempfile.mkdtemp()) / "bi.db"
os.environ["BI_DB_PATH"] = str(_DB)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from scripts import generate_data  # noqa: E402

generate_data.generate(_DB)


@pytest.fixture(autouse=True)
def _fresh_cache():
    from app import cache
    cache.clear()
    yield
