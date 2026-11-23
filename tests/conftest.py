"""테스트는 임시 폴더의 데이터(vods, kb, DB)로 돈다. 서버 모듈이 경로를 import 때 정하니 그 전에 환경을 맞춘다."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="jungle-test-"))
os.environ.update(JUNGLE_VODS=str(TMP / "vods"), JUNGLE_DB=str(TMP / "app.db"), JUNGLE_KB=str(TMP / "kb"),
                  JUNGLE_DATA=str(TMP), PYTHONUTF8="1")
(TMP / "vods").mkdir()
shutil.copytree(ROOT / "kb", TMP / "kb", ignore=shutil.ignore_patterns("quiz_log.json"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    import server.app
    from server import mine

    with TestClient(server.app.app) as c:
        # 녹화가 들어와도 실제 분석(Claude)은 돌리지 않는다
        mine.QUEUE.submit = lambda *a, **k: type("J", (), {"to_dict": lambda self: {"id": "test"}})()
        yield c


@pytest.fixture(scope="session")
def agent_headers(client):
    tok = client.post("/api/agent/token", json={}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}
