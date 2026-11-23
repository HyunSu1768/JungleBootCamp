"""성장: 판마다 판단 정확도, 최근과 이전 비교"""

import json

from server import db
from server.jobs import VODS


def test_growth_accuracy(client):
    uid = "u-growth"
    for k, (good, bad) in enumerate([(1, 3)] * 5 + [(3, 1)] * 5):
        gid = f"gr{k}"
        db.x("INSERT INTO my_games (id, user_id, dir, title, played, created, metrics) VALUES (?, ?, ?, ?, ?, ?, ?)",
             (gid, uid, f"mine/{uid}/{gid}", "t", "2026-11-01", f"2026-11-01T00:00:{k:02d}", json.dumps({"deaths_before_14": 3 - k // 5})))
        g = VODS / "mine" / uid / gid / "game1"
        g.mkdir(parents=True, exist_ok=True)
        ds = [{"verdict": "좋은 선택", "category": "갱킹"}] * good + [{"verdict": "아쉬운 선택", "category": "갱킹"}] * bad
        (g / "analysis.json").write_text(json.dumps({"version": 2, "turns": {"ally": [{"decisions": ds}]}}, ensure_ascii=False))
    r = client.get("/api/growth", headers={"X-User-Id": uid}).json()
    assert r["accuracy"] == {"recent": 0.75, "before": 0.25, "recent_n": 5, "before_n": 5}
    assert r["metrics"]["deaths14"] == {"recent": 2.0, "before": 3.0}
    assert r["weakest"]["category"] == "갱킹"
