"""예측 훈련: 한 판만 풀기, 지금 고치는 유형 먼저"""

import json

from server import db, training
from server.jobs import VODS


def _analysis(cat_bad="오브젝트"):
    def dec(i, verdict, cat):
        return {"id": f"t1-d{i}", "t": f"{i + 2}:00", "question": "q", "category": cat, "verdict": verdict,
                "options": [{"label": "a", "best": True}, {"label": "b"}]}
    return {"version": 2, "turns": {"ally": [{"id": "t1", "from": "1:30", "to": "9:00",
                                               "decisions": [dec(1, "좋은 선택", "갱킹"), dec(2, "아쉬운 선택", cat_bad), dec(3, "좋은 선택", "시야")]}]}}


def test_game_session_puts_mistakes_first():
    g = VODS / "mine" / "u-train" / "tg1" / "game1"
    g.mkdir(parents=True, exist_ok=True)
    (g / "analysis.json").write_text(json.dumps(_analysis(), ensure_ascii=False))
    items = training.build_session("u-train", 10, None, "all", game="mine/u-train/tg1/game1")
    assert [it["verdict"] for it in items][0] == "아쉬운 선택" and len(items) == 3
    assert training.build_session("someone-else", 10, None, "all", game="mine/u-train/tg1/game1") == []  # 남의 판은 안 보인다


def test_focus_categories_from_lessons():
    db.x("INSERT INTO lessons (user_id, kind, category, title, created, updated) VALUES ('u-focus', 'mistake', '시야', 't', ?, ?)", (db.now(), db.now()))
    lid = db.q("SELECT id FROM lessons WHERE user_id = 'u-focus'")[0]["id"]
    db.x("INSERT INTO lesson_hits (lesson_id, game_id, outcome, created) VALUES (?, 'x', 'again', ?)", (lid, db.now()))
    assert training.focus_categories("u-focus") == {"시야": 1}
