"""예측 훈련: 분석의 판단 포인트를 문제로 바꾸고, 간격 반복으로 낸다.

근거
- 장면을 결정 직전에 끊고 맞히게 하는 훈련(temporal occlusion)이 효과가 크다 (Müller 외 2024).
- 먼저 답하고 틀린 뒤 정답을 보면 더 잘 남고, 확신하고 틀린 것일수록 크게 고쳐진다 (Metcalfe 2017).
- 시험 보기와 간격 두고 반복하기가 가장 효과가 높은 학습 기법이다 (Dunlosky 외 2013).
- 같은 유형만 몰아서 풀지 않고 섞는다.

정답(best)은 사용자가 답한 뒤에만 내려준다.
"""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db
from .jobs import VODS

router = APIRouter(prefix="/api/train")

LEAD_SECONDS = 10   # 멈추기 전에 보여줄 영상 길이
AFTER_SECONDS = 15  # 정답 뒤 이어서 보여줄 길이


# ---------- 문제 목록 ----------
def _secs(t: str | None) -> float | None:
    if not t or not isinstance(t, str):
        return None
    try:
        total = 0.0
        for p in t.strip().split(":"):
            total = total * 60 + float(p)
        return total
    except ValueError:
        return None


def _median(xs: list[float]) -> float | None:
    s = sorted(xs)
    return s[len(s) // 2] if s else None


def _nearest_frame(gdir: Path, vod_sec: float) -> str | None:
    frames = gdir / "frames"
    if not frames.is_dir():
        return None
    best, gap = None, 1e9
    for f in frames.glob("*.jpg"):
        s = _secs(f.stem.replace("-", ":"))
        if s is not None and abs(s - vod_sec) < gap:
            best, gap = f, abs(s - vod_sec)
    return str(best.relative_to(VODS)) if best and gap < 30 else None


_cache: dict = {"at": None, "items": {}}


def _analysis_files() -> list[Path]:
    return sorted(VODS.glob("*/game*/analysis.json")) + sorted(VODS.glob("mine/*/*/game*/analysis.json"))


def catalog(force: bool = False) -> dict[str, dict]:
    """모든 분석의 판단 포인트 → 문제. 분석 파일이 바뀌면 다시 만든다."""
    files = _analysis_files()
    # 분석 파일, 영상 파일, game.json 중 하나라도 바뀌면 다시 만든다
    watched = [f for g in files for f in (g, g.parent / "video.mp4", g.parent / "game.json") if f.exists()]
    stamp = (max((f.stat().st_mtime for f in watched), default=0), len(watched))
    if not force and _cache["at"] == stamp:
        return _cache["items"]
    items: dict[str, dict] = {}
    for f in files:
        try:
            a = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if (a.get("version") or 1) < 2:
            continue
        gdir = f.parent
        rel = gdir.relative_to(VODS)
        own = rel.parts[0] == "mine"
        owner = rel.parts[1] if own else None
        meta = {}
        if (gdir / "game.json").exists():
            try:
                meta = json.loads((gdir / "game.json").read_text())
            except json.JSONDecodeError:
                pass
        base = _secs(meta.get("video_start"))
        turns = (a.get("turns") or {}).get("ally") or []
        diffs = [_secs(t.get("vod_from")) - _secs(t.get("from")) for t in turns
                 if _secs(t.get("vod_from")) is not None and _secs(t.get("from")) is not None]
        diffs += [_secs(x.get("vod")) - _secs(x.get("ingame")) for x in a.get("fights") or []
                  if _secs(x.get("vod")) is not None and _secs(x.get("ingame")) is not None]
        off = _median(diffs)
        has_video = (gdir / "video.mp4").exists() and base is not None and off is not None
        for t in turns:
            for k, d in enumerate(t.get("decisions") or [], 1):
                opts = d.get("options") or []
                if len(opts) < 2 or _secs(d.get("t")) is None:
                    continue
                best = [i for i, o in enumerate(opts) if o.get("best")]
                if not best:
                    best = [i for i, o in enumerate(opts) if o.get("chosen")]
                if len(best) != 1:
                    continue
                did = d.get("id") or f"{t.get('id')}-d{k}"
                item_id = f"{rel.as_posix()}#{did}"
                at = off + _secs(d["t"]) if off is not None else None
                items[item_id] = {
                    "id": item_id,
                    "game_ref": rel.as_posix(),
                    "turn": t.get("id"),
                    "own": own, "owner": owner,
                    "category": d.get("category") or "턴 운영",
                    "streamer": a.get("streamer"), "champion": a.get("champion"),
                    "enemy_jungler": a.get("enemy_jungler"), "context": a.get("context"),
                    "ingame": d["t"],
                    "question": d.get("question") or "어떻게 하시겠어요?",
                    "situation": d.get("situation") or "",
                    "options": [{"label": o.get("label", ""), "why": o.get("why", ""), "chosen": bool(o.get("chosen"))} for o in opts],
                    "best": best[0],
                    "verdict": d.get("verdict"),
                    "why": d.get("why"), "source": d.get("source"), "quote": d.get("quote"),
                    "result": d.get("result"), "background": d.get("background") or [],
                    "video": (str((gdir / "video.mp4").relative_to(VODS)) if has_video else None),
                    "base": base, "at": at, "ingame_offset": off,
                    "image": (d.get("frames") or [None])[0] or (_nearest_frame(gdir, at) if at else None),
                }
    _cache.update(at=stamp, items=items)
    return items


def visible(item: dict, uid: str) -> bool:
    """내 게임 문제는 그 사용자에게만"""
    return not item["own"] or item["owner"] == uid


def question_view(item: dict, order: list[int]) -> dict:
    """답하기 전 화면에 보낼 것. 정답, 결과, 이유는 빼고 선택지 순서를 섞는다"""
    keep = ("id", "game_ref", "turn", "own", "category", "streamer", "champion", "enemy_jungler", "context",
            "ingame", "question", "situation", "video", "base", "at", "ingame_offset", "image")
    v = {k: item[k] for k in keep}
    v["options"] = [{"key": i, "label": item["options"][i]["label"]} for i in order]
    v["lead"] = LEAD_SECONDS
    return v


def reveal_view(item: dict) -> dict:
    keep = ("best", "verdict", "why", "source", "quote", "result", "background")
    v = {k: item[k] for k in keep}
    v["options"] = [{"key": i, **o} for i, o in enumerate(item["options"])]
    v["after"] = AFTER_SECONDS
    return v


# ---------- 간격 반복 (SM-2를 단순화) ----------
def grade(correct: bool, confidence: int) -> int:
    if not correct:
        return 0 if confidence == 2 else 1   # 확신하고 틀림 = 가장 급함
    return 3 + confidence                  # 3 찍어서 맞힘, 4 아마, 5 확실


def schedule(uid: str, item_id: str, correct: bool, confidence: int) -> dict:
    rows = db.q("SELECT * FROM srs WHERE user_id = ? AND item_id = ?", (uid, item_id))
    s = rows[0] if rows else {"reps": 0, "interval_days": 0.0, "ease": 2.5, "lapses": 0}
    g = grade(correct, confidence)
    ease = max(1.3, s["ease"] + 0.1 - (5 - g) * (0.08 + (5 - g) * 0.02))
    if g < 3:
        reps, interval, lapses = 0, 1.0, s["lapses"] + 1   # 내일 다시
    else:
        reps = s["reps"] + 1
        interval = 1.0 if reps == 1 else 3.0 if reps == 2 else round(s["interval_days"] * ease, 1)
        if g == 3:
            interval = min(interval, 3.0)                   # 찍어서 맞힌 건 금방 다시
        lapses = s["lapses"]
    due = (dt.date.today() + dt.timedelta(days=interval)).isoformat()
    db.x("""INSERT INTO srs (user_id, item_id, reps, interval_days, ease, lapses, due, last_correct, last_confidence, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, item_id) DO UPDATE SET reps=excluded.reps, interval_days=excluded.interval_days,
              ease=excluded.ease, lapses=excluded.lapses, due=excluded.due, last_correct=excluded.last_correct,
              last_confidence=excluded.last_confidence, updated=excluded.updated""",
         (uid, item_id, reps, interval, ease, lapses, due, int(correct), confidence, db.now()))
    return {"due": due, "interval_days": interval}


# ---------- 약점 ----------
def category_stats(uid: str, days: int = 30) -> dict[str, dict]:
    since = (dt.datetime.now() - dt.timedelta(days=days)).isoformat()
    rows = db.q("""SELECT category, COUNT(*) n, SUM(correct) ok, SUM(CASE WHEN correct = 0 AND confidence = 2 THEN 1 ELSE 0 END) sure_wrong
                   FROM attempts WHERE user_id = ? AND created >= ? GROUP BY category""", (uid, since))
    return {r["category"]: {"n": r["n"], "ok": r["ok"] or 0, "sure_wrong": r["sure_wrong"] or 0,
                            "rate": round((r["ok"] or 0) / r["n"], 2)} for r in rows if r["category"]}


def own_mistake_categories(uid: str) -> dict[str, int]:
    """내 게임 분석에서 '아쉬운 선택'이 나온 카테고리별 횟수"""
    out: dict[str, int] = {}
    for it in catalog().values():
        if it["own"] and it["owner"] == uid and it["verdict"] == "아쉬운 선택":
            out[it["category"]] = out.get(it["category"], 0) + 1
    return out


# ---------- 세션 ----------
def build_session(uid: str, n: int, category: str | None, source: str) -> list[dict]:
    items = [it for it in catalog().values() if visible(it, uid)]
    if category:
        items = [it for it in items if it["category"] == category]
    if source == "mine":
        items = [it for it in items if it["own"]]
    elif source == "pro":
        items = [it for it in items if not it["own"]]
    srs = {r["item_id"]: r for r in db.q("SELECT * FROM srs WHERE user_id = ?", (uid,))}
    today = db.today()
    weak = category_stats(uid)
    mistakes = own_mistake_categories(uid)

    def priority(it: dict) -> tuple:
        s = srs.get(it["id"])
        if s:
            if s["due"] > today:
                return (9, 0, 0)  # 아직 때가 아님
            sure_wrong = s["last_correct"] == 0 and s["last_confidence"] == 2
            return (0 if sure_wrong else 1, s["due"], random.random())
        # 새 문제: 내 실수 → 내 약점 카테고리 → 나머지
        own_mistake = it["own"] and it["verdict"] == "아쉬운 선택"
        w = weak.get(it["category"], {}).get("rate", 0.6) - 0.1 * min(mistakes.get(it["category"], 0), 3)
        return (2 if own_mistake else 3, round(w, 2), random.random())

    pool = sorted((it for it in items if priority(it)[0] < 9), key=priority)[: n * 3]
    # 섞기: 같은 카테고리, 같은 판이 연달아 나오지 않게
    out: list[dict] = []
    rest = pool[:]
    while rest and len(out) < n:
        last = out[-1] if out else None
        pick = next((it for it in rest if not last or (it["category"] != last["category"] and it["game_ref"] != last["game_ref"])), rest[0])
        rest.remove(pick)
        out.append(pick)
    return out


# ---------- API ----------
@router.get("/overview")
def overview(uid: str = Depends(db.current_user)):
    items = [it for it in catalog().values() if visible(it, uid)]
    srs = {r["item_id"]: r for r in db.q("SELECT * FROM srs WHERE user_id = ?", (uid,))}
    today = db.today()
    due = sum(1 for it in items if it["id"] in srs and srs[it["id"]]["due"] <= today)
    new = sum(1 for it in items if it["id"] not in srs)
    cats: dict[str, dict] = {}
    for it in items:
        c = cats.setdefault(it["category"], {"total": 0, "due": 0, "new": 0})
        c["total"] += 1
        if it["id"] not in srs:
            c["new"] += 1
        elif srs[it["id"]]["due"] <= today:
            c["due"] += 1
    days = [r["d"] for r in db.q("SELECT DISTINCT substr(created, 1, 10) d FROM attempts WHERE user_id = ? ORDER BY d DESC", (uid,))]
    streak, day = 0, dt.date.today()
    if days and days[0] != today.__str__() and days[0] == (day - dt.timedelta(days=1)).isoformat():
        day = day - dt.timedelta(days=1)  # 오늘 아직 안 했어도 어제까지 이어졌으면 유지
    for d in days:
        if d == day.isoformat():
            streak += 1
            day -= dt.timedelta(days=1)
        elif d < day.isoformat():
            break
    today_n = db.q("SELECT COUNT(*) n, SUM(correct) ok FROM attempts WHERE user_id = ? AND created >= ?", (uid, today))[0]
    return {"total": len(items), "due": due, "new": new, "categories": cats, "streak": streak,
            "today": {"n": today_n["n"], "ok": today_n["ok"] or 0},
            "own_total": sum(1 for it in items if it["own"]), "stats": category_stats(uid)}


@router.get("/session")
def session(n: int = 10, category: str | None = None, source: str = "all", uid: str = Depends(db.current_user)):
    items = build_session(uid, max(1, min(n, 30)), category, source)
    out = []
    for it in items:
        order = list(range(len(it["options"])))
        random.shuffle(order)
        out.append(question_view(it, order))
    return {"items": out}


class Answer(BaseModel):
    item_id: str
    choice: int | None   # 원래 순서 번호, 시간 초과면 None
    confidence: int      # 0 찍음, 1 아마, 2 확실
    ms: int | None = None


@router.post("/answer")
def answer(body: Answer, uid: str = Depends(db.current_user)):
    it = catalog().get(body.item_id)
    if not it or not visible(it, uid):
        raise HTTPException(404, "문제를 찾을 수 없어요")
    conf = max(0, min(2, body.confidence))
    correct = body.choice is not None and body.choice == it["best"]
    db.x("INSERT INTO attempts (user_id, item_id, category, choice, correct, confidence, ms, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
         (uid, it["id"], it["category"], body.choice, int(correct), conf, body.ms, db.now()))
    nxt = schedule(uid, it["id"], correct, conf)
    return {"correct": correct, "next": nxt, **reveal_view(it)}


@router.get("/history")
def history(limit: int = 50, uid: str = Depends(db.current_user)):
    rows = db.q("SELECT * FROM attempts WHERE user_id = ? ORDER BY id DESC LIMIT ?", (uid, limit))
    cat = catalog()
    for r in rows:
        it = cat.get(r["item_id"])
        r["question"] = it["question"] if it else None
    return rows


def _touch() -> None:
    """테스트용: 캐시 무효화"""
    _cache["at"] = None
