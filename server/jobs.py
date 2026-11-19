"""작업 큐: 스캔, 판 분석을 한 번에 하나씩 순서대로 실행한다.

작업 상태는 vods/jobs.json에, 진행 로그는 vods/_logs/<job id>.log에 남는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import platform_util

ROOT = Path(__file__).resolve().parent.parent
VODS = Path(os.environ.get("JUNGLE_VODS", ROOT / "vods")).resolve()  # 데모, 테스트용으로 바꿀 수 있다
KB = Path(os.environ.get("JUNGLE_KB", ROOT / "kb")).resolve()
LOGS = VODS / "_logs"
JOBS_FILE = VODS / "jobs.json"
PY = sys.executable


def find_claude() -> list[str]:
    cmd = platform_util.find_claude()
    if not cmd:
        raise RuntimeError("Claude Code를 찾을 수 없어요. 설정에서 Claude를 연결해 주세요.")
    return cmd


@dataclass
class Step:
    name: str
    status: str = "waiting"  # waiting | running | done | error


@dataclass
class Job:
    id: str
    kind: str                 # scan | redetect | analyze
    url: str
    vod: str | None = None    # vods/ 아래 폴더 이름
    game: int | None = None
    status: str = "queued"    # queued | running | done | error | cancelled
    steps: list[Step] = field(default_factory=list)
    error: str | None = None
    summary: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class JobQueue:
    def __init__(self) -> None:
        LOGS.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.procs: dict[str, asyncio.subprocess.Process] = {}  # 작업 id → 지금 실행 중인 프로세스
        self.cancelled: set[str] = set()
        self._load()

    # ---------- 저장 ----------
    def _load(self) -> None:
        if not JOBS_FILE.exists():
            return
        for d in json.loads(JOBS_FILE.read_text()):
            d["steps"] = [Step(**s) for s in d["steps"]]
            job = Job(**d)
            if job.status in ("queued", "running"):
                job.status, job.error = "error", "서버가 다시 시작돼서 중단됐어요. 다시 시도해 주세요."
                for s in job.steps:
                    if s.status == "running":
                        s.status = "error"
            self.jobs[job.id] = job

    def _save(self) -> None:
        recent = sorted(self.jobs.values(), key=lambda j: j.created)[-200:]
        tmp = JOBS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps([j.to_dict() for j in recent], ensure_ascii=False, indent=1))
        tmp.replace(JOBS_FILE)

    def log_path(self, job_id: str) -> Path:
        return LOGS / f"{job_id}.log"

    def log(self, job: Job, line: str) -> None:
        with self.log_path(job.id).open("a") as f:
            f.write(line.rstrip("\n") + "\n")

    # ---------- 외부 API ----------
    def submit(self, kind: str, url: str, vod: str | None = None, game: int | None = None) -> Job:
        names = {
            "scan": ["영상 훑어보기", "판 찾기"],
            "redetect": ["판 다시 찾기"],
            "analyze": ["고화질 자료 만들기", "Claude 분석"],
            "mine": ["녹화 정리", "Claude 분석"],
        }[kind]
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, url=url, vod=vod, game=game,
                  steps=[Step(n) for n in names])
        self.jobs[job.id] = job
        self._save()
        self.queue.put_nowait(job.id)
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        if job.status == "queued":
            job.status, job.finished = "cancelled", time.time()
            self.log(job, "[취소] 시작 전에 취소했어요")
            self._save()
        elif job.status == "running":
            self.cancelled.add(job_id)
            proc = self.procs.get(job_id)
            if proc and proc.returncode is None:
                platform_util.kill_tree(proc.pid)
                # 3초 안에 안 끝나면 강제 종료
                asyncio.get_running_loop().call_later(3, self._force_kill, proc)
        return job

    @staticmethod
    def _force_kill(proc) -> None:
        if proc.returncode is None:
            platform_util.kill_tree(proc.pid, force=True)

    def active_for(self, vod: str | None = None, game: int | None = None) -> Job | None:
        for j in sorted(self.jobs.values(), key=lambda j: -j.created):
            if j.status in ("queued", "running") and j.vod == vod and (game is None or j.game == game):
                return j
        return None

    def latest_for(self, vod: str, game: int | None = None, kind: str | None = None) -> Job | None:
        for j in sorted(self.jobs.values(), key=lambda j: -j.created):
            if j.vod == vod and (game is None or j.game == game) and (kind is None or j.kind == kind):
                return j
        return None

    # ---------- 실행 ----------
    async def worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)
            if not job or job.status != "queued":
                continue
            job.status = "running"
            self._save()
            try:
                await self._run(job)
                job.status = "done"
            except Exception as e:  # noqa: BLE001
                if job.id in self.cancelled:
                    job.status, job.error = "cancelled", None
                    self.log(job, "\n[취소] 사용자가 작업을 취소했어요")
                else:
                    job.status, job.error = "error", str(e)
                    self.log(job, f"\n[오류] {e}")
                for s in job.steps:
                    if s.status == "running":
                        s.status = "cancelled" if job.status == "cancelled" else "error"
            job.finished = time.time()
            self._save()

    async def _step(self, job: Job, idx: int, coro) -> None:
        job.steps[idx].status = "running"
        self._save()
        self.log(job, f"\n━━ {job.steps[idx].name} ━━")
        await coro
        job.steps[idx].status = "done"
        self._save()

    async def _run(self, job: Job) -> None:
        if job.kind == "scan":
            await self._step(job, 0, self._scan(job))
            await self._step(job, 1, self._detect(job))
        elif job.kind == "redetect":
            await self._step(job, 0, self._detect(job))
        elif job.kind == "analyze":
            await self._step(job, 0, self._extract(job))
            await self._step(job, 1, self._analyze(job))
        elif job.kind == "mine":
            await self._step(job, 0, self._extract(job))
            await self._step(job, 1, self._analyze_mine(job))

    async def _exec(self, job: Job, cmd: list[str], on_line=None, stdin_text: str | None = None) -> None:
        self.log(job, "$ " + " ".join(c if len(c) < 80 else c[:77] + "..." for c in cmd))
        env = platform_util.claude_env()
        if job.id in self.cancelled:
            raise RuntimeError("취소됨")
        # 새 세션으로 띄워서, 취소할 때 하위 프로세스(yt-dlp, ffmpeg, claude의 셸)까지 한 번에 끈다
        # (Windows는 platform_util.hide_console_windows가 숨긴 콘솔을 붙여 창이 뜨지 않게 한다)
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT, limit=16 * 1024 * 1024, start_new_session=not platform_util.WINDOWS)
        self.procs[job.id] = proc
        if stdin_text is not None and proc.stdin:
            # 프롬프트는 명령줄 대신 표준입력으로 (Windows 명령줄 길이, 따옴표 문제를 피한다). 다 쓰면 닫아야 claude가 끝난다
            proc.stdin.write(stdin_text.encode())
            await proc.stdin.drain()
            proc.stdin.close()
        assert proc.stdout
        buf = b""
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            # yt-dlp 진행률은 \r로 갱신되므로 \r도 줄바꿈으로 본다
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                if on_line:
                    on_line(line)
                else:
                    self._log_progress(job, line)
        if buf.strip():
            (on_line or (lambda l: self._log_progress(job, l)))(buf.decode(errors="replace").strip())
        code = await proc.wait()
        self.procs.pop(job.id, None)
        if job.id in self.cancelled:
            raise RuntimeError("취소됨")
        if code != 0:
            raise RuntimeError(f"{Path(cmd[1]).name if cmd[0] == PY else Path(cmd[0]).name} 실패 (종료 코드 {code})")

    _last_progress: dict[str, float] = {}

    def _log_progress(self, job: Job, line: str) -> None:
        # 다운로드 진행률은 3초에 한 줄만 남긴다
        if line.startswith("[download]") and "%" in line:
            now = time.time()
            if now - self._last_progress.get(job.id, 0) < 3:
                return
            self._last_progress[job.id] = now
        self.log(job, line)

    # ----- 단계별 -----
    async def _scan(self, job: Job) -> None:
        def on_line(line: str) -> None:
            if line.startswith("VOD_DIR="):
                job.vod = line.split("=", 1)[1]
                self._save()
            self._log_progress(job, line)
        await self._exec(job, [PY, "tools/scan.py", job.url], on_line)
        if not job.vod:
            raise RuntimeError("VOD 폴더를 알 수 없어요")

    async def _detect(self, job: Job) -> None:
        target = str(VODS / job.vod)
        prompt = (
            f"`.claude/skills/jungle-vod/SKILL.md`와 `SCHEMA.md`를 읽고, 'A. 판 찾기'를 `{target}`에 대해 수행해. "
            f"결과는 `{target}/games.json`에 써. 사용자에게 질문하지 말고 끝까지 진행해. "
            "마지막 답변은 찾은 판 목록을 한국어로 짧게."
        )
        # 이미 추출, 분석한 판은 폴더 이름(game<n>)과 연결돼 있으니 번호를 바꾸면 안 된다
        kept = []
        for gj in sorted((VODS / job.vod).glob("game*/game.json")):
            meta = json.loads(gj.read_text())
            kept.append(f"{gj.parent.name[4:]}판(start {meta.get('start')})")
        if kept:
            prompt += (
                " 이미 자료를 만든 판이 있어: " + ", ".join(kept) + ". 이 판들은 같은 번호(n)와 시각으로 "
                "games.json에 반드시 남기고, 새로 찾은 판에는 겹치지 않는 다음 번호를 붙여."
            )
        await self._claude(job, prompt)
        if not (VODS / job.vod / "games.json").exists():
            raise RuntimeError("Claude가 games.json을 만들지 않았어요")

    async def _extract(self, job: Job) -> None:
        games = json.loads((VODS / job.vod / "games.json").read_text())["games"]
        g = next((x for x in games if x["n"] == job.game), None)
        if not g:
            raise RuntimeError(f"{job.game}판 정보가 없어요")
        cmd = [PY, "tools/extract.py", job.url, "--start", g["start"], "--end", g["end"],
               "--name", f"game{job.game}"]
        if g.get("draft_start"):
            cmd += ["--draft-start", g["draft_start"]]
        await self._exec(job, cmd)

    async def _analyze(self, job: Job) -> None:
        target = str(VODS / job.vod / f"game{job.game}")
        out = VODS / job.vod / f"game{job.game}" / "analysis.json"
        if out.exists():
            out.rename(out.with_suffix(".old.json"))
        prompt = (
            f"`.claude/skills/jungle-vod/SKILL.md`와 `SCHEMA.md`를 읽고, 'B. 판 분석'을 `{target}`에 대해 수행해. "
            f"`{target}/analysis.json`과 `{KB}/concepts.json`, `{KB}/rules.json`, `{KB}/quizzes.json`을 갱신해. "
            f"이미지 경로는 `{VODS}` 기준 상대 경로로 써. "
            "사용자에게 질문하지 말고 끝까지 진행해."
        )
        await self._claude(job, prompt)
        if not out.exists():
            raise RuntimeError("Claude가 analysis.json을 만들지 않았어요")
        json.loads(out.read_text())  # 깨진 JSON이면 여기서 오류
        # 번역투 롤 용어(플렉스, 리치, R...)를 한국 롤 유저가 쓰는 말로 한 번 더 고친다. 실패해도 분석은 살린다
        try:
            await self._exec(job, [PY, "tools/terms.py", str(out.parent), "--fix"])
        except RuntimeError:
            self.log(job, "용어 검사에서 직접 고쳐야 할 표현이 남았어요 (위 목록)")

    async def _analyze_mine(self, job: Job) -> None:
        from . import db  # 사용자 데이터는 db에
        root = VODS / job.vod
        target = root / "game1"
        out = target / "analysis.json"
        if out.exists():
            out.rename(out.with_suffix(".old.json"))
        gid = root.name
        goal = db.q("SELECT g.* FROM goals g JOIN my_games m ON m.goal_id = g.id WHERE m.id = ?", (gid,))
        user = db.q("SELECT u.* FROM users u JOIN my_games m ON m.user_id = u.id WHERE m.id = ?", (gid,))
        tier = (user[0].get("tier") if user else None) or "모름"
        prompt = (
            f"`.claude/skills/jungle-vod/SKILL.md`와 `SCHEMA.md`를 읽고, 'C. 내 게임 분석'을 `{target}`에 대해 수행해. "
            f"게임 기록은 `{root}/live.json`, 원칙은 `{KB}/rules.json`, 개념은 `{KB}/concepts.json`이야(읽기만 하고 고치지 마). "
            f"결과는 `{out}`에만 써. 이미지 경로는 `{VODS}` 기준 상대 경로로 써. 플레이어 티어: {tier}. "
            + (f"이 판 전에 플레이어가 정한 목표: \"{goal[0]['text']}\" (goal_check에 판정). " if goal else "이 판은 정한 목표가 없어. ")
            + "사용자에게 질문하지 말고 끝까지 진행해."
        )
        await self._claude(job, prompt)
        if not out.exists():
            raise RuntimeError("Claude가 analysis.json을 만들지 않았어요")
        a = json.loads(out.read_text())
        try:
            await self._exec(job, [PY, "tools/terms.py", str(target), "--fix"])
        except RuntimeError:
            self.log(job, "용어 검사에서 직접 고쳐야 할 표현이 남았어요 (위 목록)")
        # 목표 실천 여부: 사용자가 직접 고르지 않았으면 분석 판정을 넣는다
        gc = a.get("goal_check") or {}
        if goal and gc.get("followed") in ("yes", "partial", "no", "na") and not goal[0].get("followed"):
            db.x("UPDATE goals SET followed = ?, note = ? WHERE id = ?", (gc["followed"], gc.get("evidence"), goal[0]["id"]))

    async def _claude(self, job: Job, prompt: str) -> None:
        cmd = [*find_claude(), "-p", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
        state = {"result": None}

        def on_line(line: str) -> None:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                self.log(job, line)
                return
            t = ev.get("type")
            if t == "assistant":
                for c in ev.get("message", {}).get("content", []):
                    if c.get("type") == "text" and c["text"].strip():
                        self.log(job, "💬 " + c["text"].strip())
                    elif c.get("type") == "tool_use":
                        self.log(job, "· " + describe_tool(c.get("name", ""), c.get("input", {})))
            elif t == "result":
                state["result"] = ev
                cost = ev.get("total_cost_usd")
                secs = (ev.get("duration_ms") or 0) / 1000
                self.log(job, f"Claude 완료 ({secs:.0f}초" + (f", ${cost:.2f}" if cost else "") + ")")

        await self._exec(job, cmd, on_line, stdin_text=prompt)
        res = state["result"]
        if not res:
            raise RuntimeError("Claude가 결과 없이 끝났어요")
        if res.get("is_error"):
            raise RuntimeError(f"Claude 오류: {res.get('result')}")
        job.summary = (res.get("result") or "").strip()[:2000]


def short_path(p: str) -> str:
    p = str(p)
    return p.split("/vods/", 1)[-1] if "/vods/" in p else p.replace(str(ROOT) + "/", "")


def describe_tool(name: str, inp: dict) -> str:
    if name == "Read":
        return f"보는 중: {short_path(inp.get('file_path', ''))}"
    if name in ("Write", "Edit"):
        return f"쓰는 중: {short_path(inp.get('file_path', ''))}"
    if name == "Bash":
        return f"실행: {inp.get('description') or inp.get('command', '')[:100]}"
    if name in ("Glob", "Grep"):
        return f"찾는 중: {inp.get('pattern', '')}"
    if name == "Skill":
        return f"스킬: {inp.get('skill', '')}"
    return name
