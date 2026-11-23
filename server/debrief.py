"""판이 끝난 뒤 복기: 큐 잠금, 내가 먼저 하는 복기, AI 총평의 재료, 내 복기 노트(지식 축적).

흐름
1. 녹화가 들어오면(mine.register) 복기를 만들고 판이 끝난 시각부터 review_minutes(기본 10분) 동안 잠근다.
   에이전트는 상태를 보낼 때마다 lock_until을 받아, 그동안 롤 클라이언트에서 큐를 돌리면 취소한다.
2. 사용자는 AI 분석을 기다리는 동안 먼저 복기한다: 데스마다 이유, 가장 아쉬운 순간, 목표를 지켰는지.
3. 분석이 끝나면 총평 담당 Claude가 분석, 내 복기, 프로 분석 맥락(coach_context.md), 지난 복기 노트를 보고 총평을 쓴다.
4. 총평의 lessons가 내 복기 노트(lessons, lesson_hits)에 쌓인다. 같은 실수가 다시 나오면 횟수가 늘고,
   다음 판 총평과 목표 추천이 그걸 본다.

복기 노트는 사용자마다 다르니 DB에 둔다. 프로 영상의 원칙(kb/)은 공유 지식이라 여기서 고치지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from . import db
from .jobs import KB, VODS

router = APIRouter()
MIN_GAME = 300  # 5분 안에 끝난 판(다시하기)은 잠그지 않는다
REASONS = ["시야 없이 들어감", "상대 정글 위치를 몰랐음", "무리한 교전", "라인 주도권을 안 봤음", "오브젝트 싸움", "어쩔 수 없었음"]


def _base(name: str | None) -> str:
    return (name or "").split("#")[0].strip().lower()


def _mmss(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


# ================= 잠금 =================
def start(uid: str, gid: str, meta: dict) -> dict | None:
    """녹화가 들어올 때 부른다. 판이 끝난 시각 기준으로 잠근다(늦게 넘어온 녹화는 남은 시간만)"""
    prof = db.get_profile(uid)
    if (meta.get("duration") or 0) < MIN_GAME:
        return None
    lock = None
    if prof.get("review_lock", 1):
        try:
            began = dt.datetime.fromisoformat(meta["started_at"]).timestamp()
            ended = began + float(meta.get("duration") or 0)
        except (KeyError, ValueError, TypeError):
            ended = time.time()
        lock = min(ended, time.time()) + 60 * min(max(int(prof.get("review_minutes") or 10), 1), 60)
        if lock <= time.time():
            lock = None
    db.x("INSERT OR IGNORE INTO debriefs (game_id, user_id, started, lock_until) VALUES (?, ?, ?, ?)",
         (gid, uid, db.now(), lock))
    return get_row(uid, gid)


def get_row(uid: str, gid: str) -> dict | None:
    rows = db.q("SELECT * FROM debriefs WHERE game_id = ? AND user_id = ?", (gid, uid))
    return rows[0] if rows else None


def lock_until(uid: str) -> float:
    rows = db.q("SELECT MAX(lock_until) l FROM debriefs WHERE user_id = ?", (uid,))
    lu = (rows[0]["l"] if rows else None) or 0
    return lu if lu > time.time() else 0


def _brief(row: dict) -> dict:
    lu = row.get("lock_until") or 0
    return {"game_id": row["game_id"], "lock_until": lu or None, "remaining": max(0, int(lu - time.time())),
            "locked": lu > time.time(), "blocked": row["blocked"], "self_done": bool(row.get("self")), "done": row.get("done")}


@router.get("/api/debrief/active")
def active(uid: str = Depends(db.current_user)):
    """지금 잠겨 있거나, 3시간 안에 끝난 판 중 복기를 안 끝낸 가장 최근 판"""
    rows = db.q("SELECT * FROM debriefs WHERE user_id = ? ORDER BY started DESC LIMIT 1", (uid,))
    if not rows:
        return {"active": None}
    r = rows[0]
    fresh = dt.datetime.fromisoformat(r["started"]) > dt.datetime.now() - dt.timedelta(hours=3)
    if (r.get("lock_until") or 0) > time.time() or (fresh and not r.get("done")):
        return {"active": _brief(r)}
    return {"active": None}


@router.post("/api/agent/blocked")
def agent_blocked(body: dict, authorization: str | None = Header(default=None)):
    from .mine import agent_user
    uid = agent_user(authorization)
    rows = db.q("SELECT game_id FROM debriefs WHERE user_id = ? AND lock_until > ? ORDER BY started DESC LIMIT 1", (uid, time.time()))
    if rows:
        db.x("UPDATE debriefs SET blocked = blocked + 1 WHERE game_id = ?", (rows[0]["game_id"],))
    return {"ok": True, "lock_until": lock_until(uid) or None}


# ================= 복기 화면 =================
def deaths(live: dict) -> list[dict]:
    """게임 기록에서 내 데스: 인게임 시각, 누가 잡았나, 몇 명이 같이 왔나"""
    me = _base((live.get("me") or {}).get("riot_id"))
    out = []
    for e in live.get("events") or []:
        if e.get("EventName") == "ChampionKill" and _base(e.get("VictimName")) == me:
            out.append({"t": _mmss(e.get("EventTime") or 0), "sec": round(e.get("EventTime") or 0),
                        "killer": e.get("KillerName"), "assisters": len(e.get("Assisters") or [])})
    return out


def _champ(live: dict, riot_id: str | None) -> str | None:
    snaps = live.get("snapshots") or []
    for p in (snaps[-1]["players"] if snaps else []):
        if _base(p.get("riot_id")) == _base(riot_id):
            return p.get("champion")
    return None


@router.get("/api/debrief/{gid}")
def detail(gid: str, uid: str = Depends(db.current_user)):
    from .mine import _own, _view
    row = _own(uid, gid)
    view = _view(row)
    d = get_row(uid, row["id"])
    root = VODS / row["dir"]
    try:
        live = json.loads((root / "live.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        live = {}
    ds = deaths(live)
    for x in ds:
        x["killer"] = _champ(live, x["killer"]) or (x["killer"] or "").split("#")[0] or None
    analysis = None
    if view["analyzed"]:
        analysis = json.loads((root / "game1" / "analysis.json").read_text())
    return {
        **view,
        "debrief": _brief(d) if d else None,
        "self": json.loads(d["self"]) if d and d.get("self") else None,
        "deaths": ds,
        "reasons": REASONS,
        "coach": (analysis or {}).get("coach"),
        "next_goal": (analysis or {}).get("next_goal"),
        "goal_check": (analysis or {}).get("goal_check"),
    }


class SelfReview(BaseModel):
    deaths: list[dict] = []   # [{"t": "6:20", "reason": "...", "note": "..."}]
    moment: str | None = None  # 가장 아쉬운 순간
    good: str | None = None    # 잘한 것
    goal: str | None = None    # yes | partial | no | na


@router.put("/api/debrief/{gid}/self")
def save_self(gid: str, body: SelfReview, uid: str = Depends(db.current_user)):
    from .mine import _own
    row = _own(uid, gid)
    data = {"deaths": [{k: str(x.get(k) or "")[:200] for k in ("t", "reason", "note")} for x in body.deaths[:20]],
            "moment": (body.moment or "")[:500], "good": (body.good or "")[:300], "goal": body.goal,
            "at": db.now()}
    if not get_row(uid, row["id"]):
        db.x("INSERT INTO debriefs (game_id, user_id, started) VALUES (?, ?, ?)", (row["id"], uid, db.now()))
    db.x("UPDATE debriefs SET self = ? WHERE game_id = ?", (db.dumps(data), row["id"]))
    # 목표를 지켰는지는 본인 판단을 먼저 넣는다 (분석 판정은 본인이 안 골랐을 때만 들어간다)
    if body.goal in ("yes", "partial", "no", "na") and row.get("goal_id"):
        db.x("UPDATE goals SET followed = ? WHERE id = ? AND user_id = ?", (body.goal, row["goal_id"], uid))
    return {"ok": True}


@router.post("/api/debrief/{gid}/done")
def finish(gid: str, uid: str = Depends(db.current_user)):
    from .mine import _own
    row = _own(uid, gid)
    if not get_row(uid, row["id"]):
        db.x("INSERT INTO debriefs (game_id, user_id, started) VALUES (?, ?, ?)", (row["id"], uid, db.now()))
    db.x("UPDATE debriefs SET done = ? WHERE game_id = ?", (db.now(), row["id"]))
    return {"ok": True}


# ================= 내 복기 노트 =================
def lessons(uid: str, limit: int = 50) -> list[dict]:
    rows = db.q("SELECT * FROM lessons WHERE user_id = ? ORDER BY updated DESC LIMIT ?", (uid, limit))
    if not rows:
        return []
    hits = db.q(f"""SELECT h.*, m.title game_title, m.played FROM lesson_hits h LEFT JOIN my_games m ON m.id = h.game_id
                    WHERE h.lesson_id IN ({",".join("?" * len(rows))}) ORDER BY h.id""", tuple(r["id"] for r in rows))
    by: dict[int, list] = {}
    for h in hits:
        by.setdefault(h["lesson_id"], []).append(h)
    out = []
    for r in rows:
        hs = by.get(r["id"], [])
        recent = [h["outcome"] for h in hs[-5:]]
        out.append({**r, "hits": hs[-8:], "games": len({h["game_id"] for h in hs}),
                    "again": sum(h["outcome"] in ("again", "first") for h in hs),
                    "better": sum(h["outcome"] in ("better", "kept") for h in hs),
                    "trend": recent})
    # 고칠 것 중 자주 반복한 것 → 최근, 그다음 지킬 것
    out.sort(key=lambda l: l["updated"], reverse=True)
    out.sort(key=lambda l: (l["kind"] != "mistake", -l["again"] if l["kind"] == "mistake" else 0))
    return out


@router.get("/api/lessons")
def get_lessons(uid: str = Depends(db.current_user)):
    return lessons(uid)


@router.delete("/api/lessons/{lid}")
def delete_lesson(lid: int, uid: str = Depends(db.current_user)):
    db.x("DELETE FROM lesson_hits WHERE lesson_id IN (SELECT id FROM lessons WHERE id = ? AND user_id = ?)", (lid, uid))
    db.x("DELETE FROM lessons WHERE id = ? AND user_id = ?", (lid, uid))
    return {"ok": True}


def ingest(uid: str, gid: str, coach: dict) -> int:
    """총평의 lessons를 복기 노트에 쌓는다. id가 있으면 그 노트에 사례를 더하고, 없으면 새로 만든다"""
    n = 0
    db.x("DELETE FROM lesson_hits WHERE game_id = ?", (gid,))  # 다시 분석하면 이 판 사례만 바꾼다
    mine = {r["id"]: r for r in db.q("SELECT * FROM lessons WHERE user_id = ?", (uid,))}
    for le in coach.get("lessons") or []:
        if not isinstance(le, dict):
            continue
        lid = le.get("lesson_id")
        try:
            lid = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid = None
        outcome = le.get("outcome") if le.get("outcome") in ("again", "better", "first", "kept") else "first"
        kind = "strength" if le.get("kind") == "strength" else "mistake"
        if lid in mine:
            db.x("UPDATE lessons SET updated = ?, then_text = COALESCE(?, then_text) WHERE id = ?",
                 (db.now(), le.get("then") or None, lid))
        else:
            if not le.get("title"):
                continue
            lid = db.x("""INSERT INTO lessons (user_id, kind, category, title, when_text, then_text, rule_id, created, updated)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (uid, kind, le.get("category"), str(le["title"])[:80], le.get("when"), le.get("then"),
                        le.get("rule_id"), db.now(), db.now()))
            mine[lid] = {"id": lid}
        db.x("INSERT INTO lesson_hits (lesson_id, game_id, outcome, t, ref, note, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
             (lid, gid, outcome, le.get("t"), le.get("ref"), (le.get("note") or "")[:300], db.now()))
        n += 1
    return n


# ================= 총평 재료 =================
def _pro_games(exclude: Path | None = None) -> list[tuple[Path, dict]]:
    out = []
    for f in sorted(VODS.glob("*/game*/analysis.json")):
        if exclude and f.parent == exclude:  # 내 게임은 mine/<사용자>/<녹화>/game1이라 이 패턴에 안 걸린다
            continue
        try:
            a = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if a.get("own") or (a.get("version") or 1) < 2:
            continue
        out.append((f.parent, a))
    return out


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.replace(" ", "") == b.replace(" ", "")


def pro_picks(champion: str | None, enemy: str | None, n: int = 3) -> list[tuple[Path, dict, str]]:
    """내 판과 가까운 프로 판: 같은 챔피언 → 같은 상대 정글 → 상대가 내 챔피언 → 최근"""
    scored = []
    for gdir, a in _pro_games():
        why, s = [], 0
        if _same(a.get("champion"), champion):
            s += 3; why.append(f"같은 챔피언({champion})")
        if _same(a.get("enemy_jungler"), enemy):
            s += 2; why.append(f"같은 상대 정글({enemy})")
        if _same(a.get("enemy_jungler"), champion) or _same(a.get("champion"), enemy):
            s += 1; why.append("챔피언 구도가 뒤집힌 판")
        scored.append((s, gdir.stat().st_mtime, gdir, a, ", ".join(why) or "최근 분석한 프로 판"))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(g, a, w) for _, _, g, a, w in scored[:n]]


def coach_context(uid: str, gid: str, gdir: Path) -> Path:
    """총평 담당이 읽을 재료를 한 파일로: 내 복기, 지난 복기 노트, 가까운 프로 판, 프로 원칙"""
    a = json.loads((gdir / "analysis.json").read_text())
    d = get_row(uid, gid)
    lines = ["# 총평 재료", ""]

    lines += ["## 1. 플레이어가 먼저 한 복기", ""]
    me = json.loads(d["self"]) if d and d.get("self") else None
    if me:
        for x in me.get("deaths") or []:
            lines.append(f"- 데스 {x.get('t')}: {x.get('reason') or '이유 안 고름'}{' — ' + x['note'] if x.get('note') else ''}")
        if me.get("moment"):
            lines.append(f"- 가장 아쉬운 순간(본인): {me['moment']}")
        if me.get("good"):
            lines.append(f"- 잘한 것(본인): {me['good']}")
        if me.get("goal"):
            lines.append(f"- 목표를 지켰나(본인): {me['goal']}")
    else:
        lines.append("- 아직 안 했어요. self_check는 null로.")

    lines += ["", "## 2. 지난 판들에서 쌓인 복기 노트 (lesson_id로 이어 쓰기)", ""]
    ls = lessons(uid, 30)
    if ls:
        for le in ls:
            trend = " ".join({"again": "✗", "first": "✗", "better": "○", "kept": "○"}.get(t, "?") for t in le["trend"])
            lines.append(f"- lesson_id {le['id']} [{'고칠 것' if le['kind'] == 'mistake' else '지킬 것'}·{le.get('category') or '-'}] "
                         f"{le['title']}: {le.get('when_text') or ''} → {le.get('then_text') or ''} "
                         f"(판 {le['games']}개, 최근 흐름 {trend}{', 원칙 ' + le['rule_id'] if le.get('rule_id') else ''})")
    else:
        lines.append("- 아직 없어요. 이 판이 첫 복기예요.")

    lines += ["", "## 3. 가까운 프로 판 (사용자가 추가한 프로 영상 분석)", ""]
    picks = pro_picks(a.get("champion"), a.get("enemy_jungler"))
    if not picks:
        lines.append("- 분석한 프로 판이 없어요. pro는 모두 null로.")
    for pdir, pa, why in picks:
        rel = pdir.relative_to(VODS)
        vod, n = rel.parts[0], rel.parts[1].replace("game", "")
        lines.append(f"### {pa.get('streamer') or '프로'} · {pa.get('champion')} vs {pa.get('enemy_jungler')} · {pa.get('result')} "
                     f"(vod `{vod}`, game {n}) — {why}")
        if (pa.get("plan") or {}).get("jungle_plan"):
            lines.append(f"- 플랜: {pa['plan']['jungle_plan']}")
        for t in pa.get("takeaways") or []:
            lines.append(f"- 가져갈 것: {t}")
        if (pa.get("turns") or {}).get("pattern"):
            lines.append(f"- 턴 운영: {pa['turns']['pattern']}")
        for t in (pa.get("turns") or {}).get("ally") or []:
            for dc in t.get("decisions") or []:
                best = next((o.get("label") for o in dc.get("options") or [] if o.get("best")), None)
                if best:
                    lines.append(f"- [{t['id']} {dc.get('t')}] {dc.get('question')} → {best} ({dc.get('verdict')})")
        lines.append("")

    lines += ["## 4. 프로 영상에서 모은 원칙 (kb/rules.json 요약)", ""]
    try:
        rules = json.loads((KB / "rules.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        rules = []
    for r in rules:
        if r.get("category") == "밴픽":
            continue
        lines.append(f"- {r['id']} [{r.get('category')}] {r.get('when')} → {r.get('then')} (사례 {len(r.get('evidence') or [])})")
    path = gdir / "coach_context.md"
    path.write_text("\n".join(lines) + "\n")
    return path
