"""릴리스에 들어간 공유 분석을 사용자 데이터에 합치기"""

import hashlib
import json

from server import content
from server.jobs import KB, VODS


def _setup(tmp_path, monkeypatch, text="a"):
    c = tmp_path / "content"
    f = c / "vods" / "v1" / "game1" / "analysis.json"
    f.parent.mkdir(parents=True)
    f.write_text(text)
    (c / "manifest.json").write_text(json.dumps({"files": {"v1/game1/analysis.json": hashlib.sha256(text.encode()).hexdigest()[:16]}}))
    monkeypatch.setattr(content, "CONTENT", c)
    return c


def test_seed_then_keep_user_reanalysis(tmp_path, monkeypatch):
    c = _setup(tmp_path, monkeypatch)
    dst = VODS / "v1" / "game1" / "analysis.json"
    assert content.seed_vods() == 1 and dst.read_text() == "a"
    assert content.seed_vods() == 0
    dst.write_text("mine")                      # 사용자가 다시 분석
    _setup(tmp_path / "next", monkeypatch, "b")  # 새 릴리스
    assert content.seed_vods() == 0 and dst.read_text() == "mine"


def test_update_untouched(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "x1")
    dst = VODS / "v1" / "game1" / "analysis.json"
    dst.unlink(missing_ok=True)
    content.seed_vods()
    _setup(tmp_path / "next", monkeypatch, "x2")
    assert content.seed_vods() == 1 and dst.read_text() == "x2"


def test_kb_merge_by_id(tmp_path, monkeypatch):
    shared = tmp_path / "pkg"
    (shared / "kb").mkdir(parents=True)
    (shared / "content").mkdir()
    rules = json.loads((KB / "rules.json").read_text())
    rid = rules[0]["id"]
    (shared / "kb" / "rules.json").write_text(json.dumps([{"id": rid, "evidence": [{"game_ref": "new"}]}, {"id": "r-new"}]))
    monkeypatch.setattr(content, "CONTENT", shared / "content")
    assert content.merge_kb() == 1
    after = {r["id"]: r for r in json.loads((KB / "rules.json").read_text())}
    assert "r-new" in after and {"game_ref": "new"} in after[rid]["evidence"]
    assert after[rid].get("when") == rules[0].get("when")  # 사용자 것은 그대로
