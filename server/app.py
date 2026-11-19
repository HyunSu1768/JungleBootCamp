"""정글 공부 웹 서버.

    uv run uvicorn server.app:app --port 8790
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from . import platform_util
from .jobs import ROOT, VODS, JobQueue, find_claude

platform_util.hide_console_windows()
from . import mine, system
from .training import router as training_router

KB = Path(os.environ.get("JUNGLE_KB", ROOT / "kb")).resolve()
DIST = ROOT / "web" / "dist"
queue: JobQueue


@asynccontextmanager
async def lifespan(_: FastAPI):
    global queue
    VODS.mkdir(exist_ok=True)
    KB.mkdir(exist_ok=True)
    queue = JobQueue()
    mine.QUEUE = queue
    task = asyncio.create_task(queue.worker())
    system.startup()
    yield
    system.shutdown()
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(training_router)
app.include_router(mine.router)
app.include_router(system.router)


# ---------- 사용자 ----------
@app.get("/api/me")
def get_me(uid: str = Depends(db.current_user)):
    return db.get_profile(uid)


@app.put("/api/me")
def put_me(body: dict, uid: str = Depends(db.current_user)):
    return db.set_profile(uid, body)


# ---------- 도우미 ----------
def read_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def parse_time(s: str) -> float:
    total = 0.0
    for part in s.split(":"):
        total = total * 60 + float(part)
    return total


def vod_dir(name: str) -> Path:
    d = (VODS / name).resolve()
    if d.parent != VODS.resolve() or not d.is_dir():
        raise HTTPException(404, "영상을 찾을 수 없어요")
    return d


def job_view(j) -> dict | None:
    if not j:
        return None
    d = j.to_dict()
    log = queue.log_path(j.id)
    lines = log.read_text().splitlines() if log.exists() else []
    d["log_tail"] = lines[-8:]
    return d


def game_list(d: Path) -> list[dict]:
    games = read_json(d / "games.json", {}).get("games", [])
    for g in games:
        gdir = d / f"game{g['n']}"
        g["analyzed"] = (gdir / "analysis.json").exists()
        g["extracted"] = (gdir / "game.json").exists()
        try:
            g["minutes"] = round((parse_time(g["end"]) - parse_time(g["start"])) / 60)
        except (KeyError, ValueError):
            g["minutes"] = None
        g["job"] = job_view(queue.active_for(d.name, g["n"]) or queue.latest_for(d.name, g["n"], "analyze"))
    return games


def vod_summary(d: Path) -> dict:
    info = read_json(d / "info.json", {})
    games = game_list(d)
    job = queue.active_for(d.name) or queue.latest_for(d.name)
    return {
        "dir": d.name,
        "title": info.get("title", d.name),
        "uploader": info.get("uploader", ""),
        "url": info.get("url"),
        "scanned": (d / "scan" / "scan.json").exists(),
        "games": len(games),
        "jungle_games": sum(1 for g in games if g.get("jungle")),
        "analyzed": sum(1 for g in games if g["analyzed"]),
        "job": job_view(job) if job and job.kind in ("scan", "redetect") else None,
        "updated": d.stat().st_mtime,
    }


# ---------- 영상 ----------
class NewVod(BaseModel):
    url: str


@app.get("/api/vods")
def list_vods():
    dirs = [p for p in VODS.iterdir() if p.is_dir() and not p.name.startswith("_")] if VODS.exists() else []
    items = [vod_summary(d) for d in dirs if (d / "info.json").exists()]
    # 폴더가 아직 안 생긴 스캔 작업도 보여준다
    pending = [
        {"dir": None, "title": j.url, "uploader": "", "url": j.url, "scanned": False, "games": 0,
         "jungle_games": 0, "analyzed": 0, "job": job_view(j), "updated": j.created}
        for j in queue.jobs.values()
        if j.kind == "scan" and not j.vod and j.status in ("queued", "running", "error")
        and j.created > dt.datetime.now().timestamp() - 86400
    ]
    return sorted(items + pending, key=lambda x: -x["updated"])


@app.post("/api/vods")
def add_vod(body: NewVod):
    url = body.url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "링크 형식이 아니에요")
    return queue.submit("scan", url).to_dict()


@app.get("/api/vods/{name}")
def get_vod(name: str):
    d = vod_dir(name)
    s = vod_summary(d)
    s["game_list"] = game_list(d)
    s["sheets"] = read_json(d / "scan" / "scan.json", {}).get("sheets", [])
    return s


@app.post("/api/vods/{name}/redetect")
def redetect(name: str):
    d = vod_dir(name)
    if queue.active_for(name):
        raise HTTPException(409, "이미 진행 중인 작업이 있어요")
    return queue.submit("redetect", read_json(d / "info.json", {})["url"], vod=name).to_dict()


@app.post("/api/vods/{name}/games/{n}/analyze")
def analyze(name: str, n: int):
    d = vod_dir(name)
    if not any(g["n"] == n for g in read_json(d / "games.json", {}).get("games", [])):
        raise HTTPException(404, "판을 찾을 수 없어요")
    if queue.active_for(name, n):
        raise HTTPException(409, "이미 분석 중이에요")
    return queue.submit("analyze", read_json(d / "info.json", {})["url"], vod=name, game=n).to_dict()


@app.get("/api/vods/{name}/games/{n}")
def get_game(name: str, n: int):
    d = vod_dir(name)
    gdir = d / f"game{n}"
    analysis = read_json(gdir / "analysis.json", None)
    if analysis is None:
        raise HTTPException(404, "아직 분석하지 않은 판이에요")
    info = read_json(d / "info.json", {})
    games = read_json(d / "games.json", {}).get("games", [])
    return {
        "vod": {"dir": name, "title": info.get("title"), "uploader": info.get("uploader"), "url": info.get("url")},
        "game": next((g for g in games if g["n"] == n), {"n": n}),
        "meta": read_json(gdir / "game.json", {}),
        "analysis": analysis,
    }


@app.get("/api/vods/{name}/games/{n}/thumb")
def game_thumb(name: str, n: int):
    d = vod_dir(name)
    out = d / "thumbs" / f"game{n}.jpg"
    if not out.exists():
        g = next((g for g in read_json(d / "games.json", {}).get("games", []) if g["n"] == n), None)
        scan = read_json(d / "scan" / "scan.json", {})
        if not g or not scan:
            raise HTTPException(404)
        t = parse_time(g["start"]) + 240  # 게임 시작 4분 뒤 장면
        part = next((p for p in scan["parts"] if p["start"] <= t < p["start"] + p["duration"]), scan["parts"][0])
        out.parent.mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t - part['start']:.0f}",
                        "-i", str(d / "scan" / part["file"]), "-frames:v", "1", "-vf", "scale=480:-2",
                        str(out)], check=False)
        if not out.exists():
            raise HTTPException(404)
    return FileResponse(out)


# ---------- 작업 ----------
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, tail: int = 300):
    j = queue.jobs.get(job_id)
    if not j:
        raise HTTPException(404)
    d = j.to_dict()
    log = queue.log_path(j.id)
    d["log"] = log.read_text().splitlines()[-tail:] if log.exists() else []
    return d


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    if job_id not in queue.jobs:
        raise HTTPException(404)
    j = queue.jobs[job_id]
    if j.status not in ("queued", "running"):
        raise HTTPException(409, "이미 끝난 작업이에요")
    return queue.cancel(job_id).to_dict()


# ---------- 지식 ----------
def game_titles() -> dict[str, dict]:
    """game_ref → 화면에 보일 이름."""
    out = {}
    for a in VODS.glob("*/game*/analysis.json"):
        data = read_json(a, {})
        ref = f"{a.parent.parent.name}/{a.parent.name}"
        out[ref] = {"streamer": data.get("streamer"), "champion": data.get("champion"),
                    "result": data.get("result"), "path": f"/vods/{a.parent.parent.name}/{a.parent.name[4:]}"}
    return out


@app.get("/api/kb")
def get_kb():
    return {
        "concepts": read_json(KB / "concepts.json", []),
        "rules": read_json(KB / "rules.json", []),
        "quizzes": read_json(KB / "quizzes.json", []),
        "quiz_log": read_json(KB / "quiz_log.json", {}),
        "games": game_titles(),
    }


class QuizResult(BaseModel):
    result: str  # O | △ | X
    answer: str = ""


@app.post("/api/quiz/{qid}/result")
def save_result(qid: str, body: QuizResult):
    if body.result not in ("O", "△", "X"):
        raise HTTPException(400)
    p = KB / "quiz_log.json"
    log = read_json(p, {})
    log.setdefault(qid, []).append({"date": dt.date.today().isoformat(), "result": body.result,
                                    "answer": body.answer[:1000]})
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    tmp.replace(p)
    return log[qid]


class QuizAnswer(BaseModel):
    answer: str


@app.post("/api/quiz/{qid}/feedback")
async def quiz_feedback(qid: str, body: QuizAnswer):
    quiz = next((q for q in read_json(KB / "quizzes.json", []) if q["id"] == qid), None)
    if not quiz:
        raise HTTPException(404)
    prompt = (
        "롤 정글 복습 문제에 대한 사용자의 답을 채점해 줘. 파일을 고치지 말고 답변만 해.\n"
        f"문제 장면 이미지: {VODS / quiz['image']} (필요하면 Read로 봐)\n"
        f"문제 JSON: {json.dumps(quiz, ensure_ascii=False)}\n"
        f"사용자 답: {body.answer}\n\n"
        "해요체로 4문장 이내. 첫 문장은 '맞았어요', '거의 맞았어요', '아쉬워요' 중 하나로 시작하고, "
        "정답과 다르더라도 근거가 타당하면 인정해. 놓친 판단 기준이 있으면 하나만 짚어 줘."
    )
    try:
        claude = find_claude()
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from None
    proc = await asyncio.create_subprocess_exec(
        *claude, "-p", "--output-format", "json", "--dangerously-skip-permissions",
        cwd=ROOT, env=platform_util.claude_env(), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=240)
    except TimeoutError:
        proc.kill()
        raise HTTPException(504, "Claude 응답이 너무 오래 걸려요") from None
    try:
        return {"feedback": json.loads(out)["result"].strip()}
    except (json.JSONDecodeError, KeyError):
        raise HTTPException(500, "Claude 응답을 읽지 못했어요") from None


# ---------- 정적 파일 ----------
@app.middleware("http")
async def guard_media(request, call_next):
    # 올리는 중인 파일, 녹화 원본, 로그는 내보내지 않는다.
    # TODO 실서비스: /media/mine/<사용자>/는 로그인 사용자 본인만 (서명된 URL이나 쿠키 세션으로)
    p = request.url.path
    if p.startswith("/media/") and (p.startswith(("/media/_uploads", "/media/_logs", "/media/_recordings"))
                                     or p.endswith((".mkv", ".part", "jobs.json"))):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)


app.mount("/media", StaticFiles(directory=VODS, check_dir=False), name="media")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    f = (DIST / path).resolve()
    if path and f.is_file() and DIST.resolve() in f.parents:
        return FileResponse(f)
    index = DIST / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "web/dist가 없어요. ./run.sh로 실행해 주세요."}, status_code=503)
    return FileResponse(index)
