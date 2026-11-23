"""성장: 실력이 실제로 늘고 있는지 숫자로 본다.

내 게임 분석의 판단 포인트(좋은 선택 / 아쉬운 선택)가 가장 직접적인 실력 지표다. 판마다 판단 정확도를 내고,
최근 5판과 그 전 5판을 비교한다. 같이 보는 것: 목표 실천, 복기 노트(고친 실수, 반복 중인 실수), 예측 훈련 정답률,
게임 기록 지표(10분 CS, 14분 전 데스). 유형별로 내 게임과 훈련을 나란히 놓아 가장 약한 유형을 고른다.
"""

from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends

from . import db
from .jobs import VODS

router = APIRouter()
WINDOW = 5


def _decisions(a: dict) -> list[dict]:
    return [d for t in (a.get("turns") or {}).get("ally") or [] for d in t.get("decisions") or []]


def _avg(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


@router.get("/api/growth")
def growth(uid: str = Depends(db.current_user)):
    rows = db.q("SELECT * FROM my_games WHERE user_id = ? ORDER BY created", (uid,))
    goal_of = {r["game_id"]: r["followed"] for r in db.q("SELECT game_id, followed FROM goals WHERE user_id = ? AND game_id IS NOT NULL", (uid,))}
    hits: dict[str, dict] = {}
    for h in db.q("""SELECT h.game_id, h.outcome FROM lesson_hits h JOIN lessons l ON l.id = h.lesson_id
                     WHERE l.user_id = ? AND l.kind = 'mistake'""", (uid,)):
        g = hits.setdefault(h["game_id"], {"again": 0, "better": 0, "first": 0})
        if h["outcome"] in g:
            g[h["outcome"]] += 1

    games, cats = [], {}
    for r in rows[-40:]:
        m = json.loads(r["metrics"] or "{}")
        try:
            a = json.loads((VODS / r["dir"] / "game1" / "analysis.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            a = None
        ds = _decisions(a) if a else []
        good = sum(d.get("verdict") == "좋은 선택" for d in ds)
        bad = sum(d.get("verdict") == "아쉬운 선택" for d in ds)
        games.append({
            "id": r["id"], "played": r["played"], "champion": r["champion"], "result": r["result"], "role": r["role"],
            "analyzed": a is not None, "good": good, "bad": bad,
            "accuracy": round(good / (good + bad), 3) if good + bad else None,
            "goal": goal_of.get(r["id"]), **hits.get(r["id"], {"again": 0, "better": 0, "first": 0}),
            "cs10": m.get("cs10"), "deaths14": m.get("deaths_before_14"),
        })
    analyzed = [g for g in games if g["accuracy"] is not None]
    recent, before = analyzed[-WINDOW:], analyzed[-2 * WINDOW:-WINDOW]

    # 유형별: 최근 10판의 내 판단 + 30일 훈련 정답률
    for r in rows[-10:]:
        try:
            a = json.loads((VODS / r["dir"] / "game1" / "analysis.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        for d in _decisions(a):
            c = cats.setdefault(d.get("category") or "턴 운영", {"good": 0, "bad": 0})
            if d.get("verdict") == "좋은 선택":
                c["good"] += 1
            elif d.get("verdict") == "아쉬운 선택":
                c["bad"] += 1
    from .training import category_stats
    train = category_stats(uid)
    categories = []
    for c in sorted(set(cats) | set(train)):
        g = cats.get(c, {"good": 0, "bad": 0})
        n = g["good"] + g["bad"]
        t = train.get(c)
        categories.append({"category": c, "game_n": n, "game_rate": round(g["good"] / n, 2) if n else None,
                           "train_n": t["n"] if t else 0, "train_rate": t["rate"] if t else None})
    # 가장 약한 유형: 판단이 3개 이상 쌓인 것 중 내 게임 정확도(없으면 훈련 정답률)가 가장 낮은 것
    scored = [c for c in categories if (c["game_n"] >= 3 and c["game_rate"] is not None) or (c["train_n"] >= 5 and c["train_rate"] is not None)]
    weakest = min(scored, key=lambda c: c["game_rate"] if c["game_n"] >= 3 else c["train_rate"], default=None)

    # 복기 노트: 최근 두 번 연속 나아진 실수 = 고친 것, 마지막이 또 나옴 = 반복 중
    lessons = db.q("SELECT id, title FROM lessons WHERE user_id = ? AND kind = 'mistake'", (uid,))
    fixed, repeating = [], []
    for le in lessons:
        oc = [h["outcome"] for h in db.q("SELECT outcome FROM lesson_hits WHERE lesson_id = ? ORDER BY id", (le["id"],))]
        if len(oc) >= 2 and oc[-2:] == ["better", "better"]:
            fixed.append(le["title"])
        elif oc and oc[-1] == "again":
            repeating.append(le["title"])

    # 예측 훈련: 주마다 정답률 (최근 8주)
    since = (dt.date.today() - dt.timedelta(weeks=8)).isoformat()
    weeks: dict[str, dict] = {}
    for a in db.q("SELECT created, correct FROM attempts WHERE user_id = ? AND created >= ?", (uid, since)):
        d = dt.date.fromisoformat(a["created"][:10])
        w = weeks.setdefault((d - dt.timedelta(days=d.weekday())).isoformat(), {"n": 0, "ok": 0})
        w["n"] += 1
        w["ok"] += a["correct"]
    train_weeks = [{"week": k, "n": v["n"], "rate": round(v["ok"] / v["n"], 2)} for k, v in sorted(weeks.items())]

    goals = [g["goal"] for g in games if g["goal"] in ("yes", "partial", "no")]
    return {
        "games": games,
        "accuracy": {"recent": _avg([g["accuracy"] for g in recent]), "before": _avg([g["accuracy"] for g in before]),
                     "recent_n": len(recent), "before_n": len(before)},
        "goal_rate": round(sum(g == "yes" for g in goals[-10:]) / len(goals[-10:]), 2) if goals else None,
        "goal_n": len(goals[-10:]),
        "lessons": {"fixed": fixed, "repeating": repeating, "total": len(lessons)},
        "categories": categories, "weakest": weakest,
        "train_weeks": train_weeks,
        "metrics": {"cs10": {"recent": _avg([g["cs10"] for g in games[-WINDOW:]]), "before": _avg([g["cs10"] for g in games[-2 * WINDOW:-WINDOW]])},
                    "deaths14": {"recent": _avg([g["deaths14"] for g in games[-WINDOW:]]), "before": _avg([g["deaths14"] for g in games[-2 * WINDOW:-WINDOW]])}},
    }
