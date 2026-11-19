"""내 게임: 녹화 에이전트 연결, 녹화 받기, 게임 기록 지표, 판 전 목표.

에이전트(agent/recorder.py)는 사용자 PC에서 돌며 롤 게임을 자동 녹화한다.
웹에서 연결 토큰을 받아 넣으면, 녹화가 끝날 때마다 영상과 게임 기록(live.json)을 여기로 보낸다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db, training
from .jobs import KB, ROOT, VODS

router = APIRouter()
QUEUE = None  # app.py가 시작할 때 넣어 준다 (작업 큐)
MINE = VODS / "mine"
UPLOADS = VODS / "_uploads"
STATUS: dict[str, dict] = {}  # 사용자 → 에이전트 마지막 상태 (메모리. 서버를 여러 대로 늘리면 Redis로)
# 같은 PC 모드(파일 경로만 넘기기)는 서버와 에이전트가 한 PC일 때만 의미가 있다. 실서비스에선 끈다
ALLOW_LOCAL_PATHS = os.environ.get("JUNGLE_LOCAL_AGENT", "1") == "1"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def agent_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "연결 토큰이 없어요")
    rows = db.q("SELECT user_id FROM agent_tokens WHERE hash = ?", (_hash(authorization[7:].strip()),))
    if not rows:
        raise HTTPException(401, "연결 토큰이 맞지 않아요. 웹에서 새로 받아 주세요")
    return rows[0]["user_id"]


def _safe_id(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9-]", "", s)[:40]
    if not s:
        raise HTTPException(400, "녹화 id가 이상해요")
    return s


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


# ================= 에이전트 =================
@router.get("/api/agent")
def agent_info(request: Request, uid: str = Depends(db.current_user)):
    st = STATUS.get(uid)
    online = bool(st and time.time() - st["at"] < 20 and st.get("state") != "off")
    tokens = db.q("SELECT label, created, last_seen FROM agent_tokens WHERE user_id = ? ORDER BY created DESC", (uid,))
    port = request.url.port or 8790
    return {"online": online, "status": st if online else None, "tokens": tokens,
            "server": f"http://{_lan_ip()}:{port}", "local_server": f"http://127.0.0.1:{port}"}


@router.post("/api/agent/token")
def new_token(body: dict | None = None, uid: str = Depends(db.current_user)):
    token = secrets.token_urlsafe(24)
    db.x("INSERT INTO agent_tokens (hash, user_id, label, created) VALUES (?, ?, ?, ?)",
         (_hash(token), uid, (body or {}).get("label") or "내 PC", db.now()))
    return {"token": token}  # 원문은 지금 한 번만 보여준다


@router.delete("/api/agent/tokens")
def revoke_tokens(uid: str = Depends(db.current_user)):
    db.x("DELETE FROM agent_tokens WHERE user_id = ?", (uid,))
    STATUS.pop(uid, None)
    return {"ok": True}


@router.get("/api/agent/recorder.py")
def agent_script():
    """Windows PC에서 바로 내려받게 (curl -o recorder.py http://<서버>/api/agent/recorder.py)"""
    return FileResponse(ROOT / "agent" / "recorder.py", media_type="text/x-python", filename="recorder.py")


@router.post("/api/agent/status")
def agent_status(body: dict, authorization: str | None = Header(default=None)):
    uid = agent_user(authorization)
    STATUS[uid] = {**{k: body.get(k) for k in ("state", "version", "platform", "game_time", "champion", "elapsed", "pending")}, "at": time.time()}
    db.x("UPDATE agent_tokens SET last_seen = ? WHERE hash = ?", (db.now(), _hash(authorization[7:].strip())))
    return {"ok": True}


def _part(uid: str, rec: str) -> Path:
    d = UPLOADS / uid
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe_id(rec)}.part"


@router.get("/api/agent/uploads/{rec}")
def upload_size(rec: str, uid: str = Depends(agent_user)):
    p = _part(uid, rec)
    return {"size": p.stat().st_size if p.exists() else 0}


MAX_UPLOAD = 8 << 30  # 8GB


@router.put("/api/agent/uploads/{rec}")
async def upload_chunk(rec: str, request: Request, offset: int, total: int, uid: str = Depends(agent_user)):
    if total > MAX_UPLOAD:
        raise HTTPException(413, "녹화 파일이 너무 커요")
    p = _part(uid, rec)
    size = p.stat().st_size if p.exists() else 0
    if offset != size:
        return {"size": size}  # 어긋나면 서버가 가진 크기를 알려 주고, 에이전트가 거기부터 다시 보낸다
    with p.open("ab") as f:
        async for chunk in request.stream():
            f.write(chunk)
            if f.tell() > total:
                break
    return {"size": p.stat().st_size}


class Delivery(BaseModel):
    meta: dict
    path: str | None = None    # 같은 PC 모드
    upload: str | None = None  # 올린 녹화 id


@router.post("/api/agent/recordings")
def receive(body: Delivery, uid: str = Depends(agent_user)):
    meta = body.meta
    gid = _safe_id(str(meta.get("id") or ""))
    root = MINE / uid / gid
    if db.q("SELECT 1 FROM my_games WHERE id = ? AND user_id = ?", (gid, uid)):
        return {"id": gid, "duplicate": True}
    root.mkdir(parents=True, exist_ok=True)
    src = root / "recording.mkv"
    if body.upload:
        part = _part(uid, body.upload)
        if not part.exists():
            raise HTTPException(400, "올린 파일이 없어요")
        part.replace(src)
    elif body.path and ALLOW_LOCAL_PATHS:
        p = Path(body.path)
        if p.name != "recording.mkv" or not (p.parent / "live.json").exists():
            raise HTTPException(400, "에이전트 녹화 폴더가 아니에요")
        shutil.move(str(p), src)
    else:
        raise HTTPException(400, "녹화 파일이 없어요")
    return register(uid, gid, root, meta)


# ================= 등록, 지표 =================
def _base(name: str | None) -> str:
    return (name or "").split("#")[0].strip().lower()


def role_of(me: dict) -> str | None:
    pos = (me or {}).get("position")
    if pos:
        return {"TOP": "탑", "JUNGLE": "정글", "MIDDLE": "미드", "BOTTOM": "원딜", "UTILITY": "서폿"}.get(pos, pos)
    spells = " ".join(s or "" for s in (me or {}).get("spells") or [])
    return "정글" if re.search(r"강타|Smite", spells) else None


OBJ_NAMES = {"DragonKill": "드래곤", "HordeKill": "공허 유충", "HeraldKill": "전령", "BaronKill": "바론",
             "AtakhanKill": "아타칸", "TurretKilled": "포탑", "InhibKilled": "억제기"}


def compute_metrics(live: dict) -> dict:
    me_id = _base((live.get("me") or {}).get("riot_id"))
    snaps = live.get("snapshots") or []
    events = live.get("events") or []
    last = snaps[-1]["players"] if snaps else []
    team_of = {_base(p["riot_id"]): p["team"] for p in last}
    my_team = team_of.get(me_id)
    me = next((p for p in last if _base(p["riot_id"]) == me_id), None)

    def cs_at(sec: float) -> int | None:
        best = min(snaps, key=lambda s: abs(s["t"] - sec), default=None)
        if not best or abs(best["t"] - sec) > 20:
            return None
        p = next((p for p in best["players"] if _base(p["riot_id"]) == me_id), None)
        return (p or {}).get("scores", {}).get("creepScore")

    kills = [e for e in events if e.get("EventName") == "ChampionKill"]
    mine_kills = lambda e: _base(e.get("KillerName")) == me_id or me_id in {_base(a) for a in e.get("Assisters") or []}  # noqa: E731
    team_kills = [e for e in kills if team_of.get(_base(e.get("KillerName"))) == my_team]
    objectives: dict[str, dict] = {}
    for e in events:
        name = OBJ_NAMES.get(e.get("EventName"))
        if not name or e.get("EventName") in ("TurretKilled", "InhibKilled"):
            continue
        side = "ally" if team_of.get(_base(e.get("KillerName"))) == my_team else "enemy"
        o = objectives.setdefault(name, {"ally": 0, "enemy": 0})
        o[side] += 1
    end = next((e["EventTime"] for e in events if e.get("EventName") == "GameEnd"), snaps[-1]["t"] if snaps else None)
    sc = (me or {}).get("scores") or {}
    return {
        "result": live.get("result"),
        "champion": (live.get("me") or {}).get("champion") or (me or {}).get("champion"),
        "role": role_of(live.get("me") or {}),
        "minutes": round(end / 60, 1) if end else None,
        "kda": [sc.get("kills"), sc.get("deaths"), sc.get("assists")] if sc else None,
        "cs10": cs_at(600), "cs14": cs_at(840),
        "deaths_before_14": sum(1 for e in kills if _base(e.get("VictimName")) == me_id and e["EventTime"] < 840),
        "early_takedowns": sum(1 for e in kills if e["EventTime"] < 480 and mine_kills(e)),
        "kp": round(sum(1 for e in team_kills if mine_kills(e)) / len(team_kills), 2) if team_kills else None,
        "vision": sc.get("wardScore"),
        "objectives": objectives,
        "late_start": live.get("late_start"),
    }


def _hms(sec: float) -> str:
    sec = int(round(max(0, sec)))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def active_goal(uid: str) -> dict | None:
    rows = db.q("SELECT * FROM goals WHERE user_id = ? AND game_id IS NULL ORDER BY id DESC LIMIT 1", (uid,))
    return rows[0] if rows else None


def register(uid: str, gid: str, root: Path, meta: dict) -> dict:
    (root / "live.json").write_text(json.dumps(meta, ensure_ascii=False))
    m = compute_metrics(meta)
    off = meta.get("offset") or 0
    duration = meta.get("duration") or 0
    title = f"{m['champion'] or '?'}{' · ' + m['result'] if m['result'] else ''}"
    (root / "info.json").write_text(json.dumps({"title": title, "uploader": (meta.get("me") or {}).get("riot_id", ""),
                                                "url": str(root / "recording.mkv"), "mine": True}, ensure_ascii=False))
    (root / "games.json").write_text(json.dumps({"games": [{
        "n": 1, "start": _hms(off), "end": _hms(duration), "champion": m["champion"], "role": m["role"],
        "result": m["result"], "context": "솔로랭크",
        "note": "롤 클라이언트 기록으로 시각을 맞췄어요. 녹화 초 = 인게임 초 + offset",
    }]}, ensure_ascii=False, indent=1))
    goal = active_goal(uid)
    played = (meta.get("started_at") or db.now())[:10]
    db.x("""INSERT INTO my_games (id, user_id, dir, title, champion, result, played, created, goal_id, metrics, role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
         (gid, uid, str(root.relative_to(VODS)), title, m["champion"], m["result"], played, db.now(),
          goal["id"] if goal else None, db.dumps(m), m["role"]))
    if goal:
        db.x("UPDATE goals SET game_id = ? WHERE id = ?", (gid, goal["id"]))
    job = None
    prof = db.get_profile(uid)
    # 정글 판만 자동 분석 (분석 1회에 비용이 드니 정글이 아닌 판은 사용자가 원할 때만)
    if prof.get("auto_analyze", 1) and m["role"] in ("정글", None) and duration > 300:
        job = QUEUE.submit("mine", str(root / "recording.mkv"), vod=str(root.relative_to(VODS)), game=1).to_dict()
    return {"id": gid, "metrics": m, "job": job}


# ================= 웹: 내 게임 =================
def _own(uid: str, gid: str) -> dict:
    rows = db.q("SELECT * FROM my_games WHERE id = ? AND user_id = ?", (_safe_id(gid), uid))
    if not rows:
        raise HTTPException(404, "내 게임을 찾을 수 없어요")
    return rows[0]


def _view(row: dict) -> dict:
    from .app import job_view  # 순환 import 피하기
    vod = row["dir"]
    gdir = VODS / vod / "game1"
    goal = db.q("SELECT * FROM goals WHERE id = ?", (row["goal_id"],))[0] if row.get("goal_id") else None
    return {
        **{k: row[k] for k in ("id", "title", "champion", "result", "played", "role", "created")},
        "metrics": json.loads(row["metrics"] or "{}"),
        "analyzed": (gdir / "analysis.json").exists(),
        "job": job_view(QUEUE.active_for(vod, 1) or QUEUE.latest_for(vod, 1)),
        "goal": goal,
        "thumb": f"{vod}/game1/frames" if (gdir / "frames").exists() else None,
    }


@router.get("/api/mine")
def my_games(limit: int = 50, uid: str = Depends(db.current_user)):
    rows = db.q("SELECT * FROM my_games WHERE user_id = ? ORDER BY created DESC LIMIT ?", (uid, limit))
    return [_view(r) for r in rows]


@router.get("/api/mine/{gid}")
def my_game(gid: str, uid: str = Depends(db.current_user)):
    row = _own(uid, gid)
    v = _view(row)
    gdir = VODS / row["dir"] / "game1"
    analysis = json.loads((gdir / "analysis.json").read_text()) if v["analyzed"] else None
    meta = json.loads((gdir / "game.json").read_text()) if (gdir / "game.json").exists() else {}
    return {
        **v,
        "vod": {"dir": row["dir"], "title": row["title"], "uploader": "내 게임", "url": None, "mine": True},
        "game": {"n": 1}, "meta": meta, "analysis": analysis,
    }


@router.post("/api/mine/{gid}/analyze")
def analyze_mine(gid: str, uid: str = Depends(db.current_user)):
    row = _own(uid, gid)
    if QUEUE.active_for(row["dir"], 1):
        raise HTTPException(409, "이미 분석 중이에요")
    return QUEUE.submit("mine", str(VODS / row["dir"] / "recording.mkv"), vod=row["dir"], game=1).to_dict()


@router.delete("/api/mine/{gid}")
def delete_mine(gid: str, uid: str = Depends(db.current_user)):
    row = _own(uid, gid)
    shutil.rmtree(VODS / row["dir"], ignore_errors=True)
    db.x("DELETE FROM my_games WHERE id = ?", (row["id"],))
    return {"ok": True}


@router.get("/api/mine-stats")
def my_stats(weeks: int = 4, uid: str = Depends(db.current_user)):
    """주간 지표: 정글 판만"""
    since = (dt.date.today() - dt.timedelta(weeks=weeks)).isoformat()
    rows = db.q("SELECT played, metrics, goal_id FROM my_games WHERE user_id = ? AND played >= ? ORDER BY played", (uid, since))
    weeks_out: dict[str, dict] = {}
    for r in rows:
        m = json.loads(r["metrics"] or "{}")
        if m.get("role") not in ("정글", None):
            continue
        d = dt.date.fromisoformat(r["played"])
        wk = (d - dt.timedelta(days=d.weekday())).isoformat()
        w = weeks_out.setdefault(wk, {"week": wk, "games": 0, "wins": 0, "cs10": [], "deaths14": [], "early": [], "obj_ally": 0, "obj_all": 0})
        w["games"] += 1
        w["wins"] += m.get("result") == "승"
        if m.get("cs10") is not None:
            w["cs10"].append(m["cs10"])
        w["deaths14"].append(m.get("deaths_before_14") or 0)
        w["early"].append(m.get("early_takedowns") or 0)
        for o in (m.get("objectives") or {}).values():
            w["obj_ally"] += o["ally"]
            w["obj_all"] += o["ally"] + o["enemy"]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    out = []
    for w in weeks_out.values():
        out.append({"week": w["week"], "games": w["games"], "win_rate": round(w["wins"] / w["games"], 2),
                    "cs10": avg(w["cs10"]), "deaths_before_14": avg(w["deaths14"]), "early_takedowns": avg(w["early"]),
                    "objective_share": round(w["obj_ally"] / w["obj_all"], 2) if w["obj_all"] else None})
    goals = db.q("SELECT followed, COUNT(*) n FROM goals WHERE user_id = ? AND game_id IS NOT NULL AND created >= ? GROUP BY followed", (uid, since))
    return {"weeks": out, "goals": {(g["followed"] or "unknown"): g["n"] for g in goals}}


# ================= 판 전 목표 =================
def _rules() -> list[dict]:
    try:
        return json.loads((KB / "rules.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@router.get("/api/goals")
def goals(uid: str = Depends(db.current_user)):
    history = db.q("""SELECT g.*, m.title game_title, m.played FROM goals g LEFT JOIN my_games m ON m.id = g.game_id
                      WHERE g.user_id = ? AND g.game_id IS NOT NULL ORDER BY g.id DESC LIMIT 20""", (uid,))
    # 추천: 내 게임에서 아쉬운 선택이 많았던 유형 → 훈련에서 약한 유형 → 나머지. 판 중에 떠올릴 수 있게 '이러면 → 이렇게' 하나만
    mistakes = training.own_mistake_categories(uid)
    weak = {c: s["rate"] for c, s in training.category_stats(uid).items() if s["n"] >= 3}
    rules = [r for r in _rules() if r.get("category") != "밴픽" and r.get("when") and r.get("then")]
    rules.sort(key=lambda r: (-mistakes.get(r.get("category"), 0), weak.get(r.get("category"), 1.0)))
    suggestions = [{"rule_id": r["id"], "category": r.get("category"), "when": r["when"], "then": r["then"],
                    "why": ("내 게임에서 자주 아쉬웠던 유형" if mistakes.get(r.get("category")) else
                            "훈련에서 약한 유형" if r.get("category") in weak and weak[r["category"]] < 0.6 else None)}
                   for r in rules[:6]]
    return {"active": active_goal(uid), "history": history, "suggestions": suggestions}


class GoalIn(BaseModel):
    text: str
    rule_id: str | None = None


@router.post("/api/goals")
def set_goal(body: GoalIn, uid: str = Depends(db.current_user)):
    text = body.text.strip()[:200]
    if not text:
        raise HTTPException(400, "목표를 적어 주세요")
    db.x("DELETE FROM goals WHERE user_id = ? AND game_id IS NULL", (uid,))  # 다음 판 목표는 하나만
    db.x("INSERT INTO goals (user_id, rule_id, text, created) VALUES (?, ?, ?, ?)", (uid, body.rule_id, text, db.now()))
    return active_goal(uid)


class GoalCheck(BaseModel):
    followed: str  # yes | partial | no | na
    note: str | None = None


@router.put("/api/goals/{goal_id}")
def check_goal(goal_id: int, body: GoalCheck, uid: str = Depends(db.current_user)):
    if body.followed not in ("yes", "partial", "no", "na"):
        raise HTTPException(400, "followed 값이 이상해요")
    db.x("UPDATE goals SET followed = ?, note = ? WHERE id = ? AND user_id = ?", (body.followed, body.note, goal_id, uid))
    return {"ok": True}


@router.delete("/api/goals/active")
def clear_goal(uid: str = Depends(db.current_user)):
    db.x("DELETE FROM goals WHERE user_id = ? AND game_id IS NULL", (uid,))
    return {"ok": True}
