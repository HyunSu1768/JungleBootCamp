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

from . import parallel, platform_util

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
        self.procs: dict[str, set] = {}  # 작업 id → 지금 실행 중인 프로세스들 (분석은 여러 Claude가 동시에 돈다)
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
            "analyze": ["고화질 자료 만들기", "Claude 분석", "지식 정리"],
            "mine": ["녹화 정리", "Claude 분석", "총평"],
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
            for proc in list(self.procs.get(job_id, ())):
                if proc.returncode is None:
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
            if len(job.steps) > 2:  # 분석은 이미 보이고, 판을 넘는 지식(kb)만 뒤에서 정리
                await self._step(job, 2, self._update_kb(job))
        elif job.kind == "mine":
            await self._step(job, 0, self._extract(job))
            await self._step(job, 1, self._analyze_mine(job))
            if len(job.steps) > 2:  # 분석이 나온 뒤 판 전체 총평과 복기 노트
                await self._step(job, 2, self._coach(job))

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
        self.procs.setdefault(job.id, set()).add(proc)
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
        self.procs.get(job.id, set()).discard(proc)
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
        gdir = VODS / job.vod / f"game{job.game}"
        a = await self._analyze_parallel(job, gdir, "pro")
        job.summary = "\n".join(f"{i}. {t}" for i, t in enumerate(a.get("takeaways") or [], 1))[:2000] or job.summary

    async def _analyze_parallel(self, job: Job, gdir: Path, mode: str, extra: str = "") -> dict:
        """담당별 Claude를 동시에 돌리고 조각을 합쳐 analysis.json을 쓴다"""
        out = gdir / "analysis.json"
        pdir = gdir / "parts"
        if pdir.exists():
            for f in pdir.glob("*.json"):
                f.unlink()
        pdir.mkdir(exist_ok=True)
        ws = parallel.workers(gdir, mode)
        # 예전 분석이 폴더에 있으면 담당들이 새로 보지 않고 옮겨 적는다. 분석하는 동안 폴더 밖에 치워 둔다
        prev = [(f, LOGS / f"{job.id}.{f.name}") for f in (out, out.with_suffix(".old.json")) if f.exists()]
        for f, dst in prev:
            f.replace(dst)
        self.log(job, "담당을 나눠 동시에 분석해요: " + ", ".join(w.label for w in ws))
        started = time.time()
        costs: list[float] = []

        effort = analysis_effort()
        self.log(job, f"분석 방식: {'꼼꼼하게' if effort != 'low' else '빠르게'} (Claude effort {effort})")

        async def run(w: parallel.Worker) -> None:
            text = parallel.prompt(w, gdir, mode, VODS, KB, extra)
            for attempt in (1, 2):
                try:
                    res = await self._claude(job, text, tag=w.label, effort=effort)
                    costs.append(res.get("total_cost_usd") or 0)
                    parallel.load_part(gdir, w)
                    return
                except Exception as e:  # noqa: BLE001
                    if job.id in self.cancelled or attempt == 2:
                        raise RuntimeError(f"{w.label} 담당 실패: {e}") from e
                    self.log(job, f"[{w.label}] 다시 시도해요: {e}")

        results = await asyncio.gather(*(run(w) for w in ws), return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        if not errors:
            # 담당이 턴을 건너뛰었으면 빈 구간만 다시 맡긴다
            holes = parallel.gaps(gdir, ws, parallel.game_minutes(gdir))
            if holes:
                fix = [parallel.turn_worker(gdir, f"turns-fix{i}", f"f{i}", a, b) for i, (a, b) in enumerate(holes, 1)]
                self.log(job, "빠진 턴이 있어서 채워요: " + ", ".join(f"{parallel.mmss(a)}~{parallel.mmss(b)}" for a, b in holes))
                results = await asyncio.gather(*(run(w) for w in fix), return_exceptions=True)
                errors = [r for r in results if isinstance(r, BaseException)]
                ws = ws + fix
        try:
            if errors:
                raise errors[0]
            a = parallel.merge(gdir, ws, mode)
        except BaseException:
            for f, dst in prev:  # 실패하면 예전 분석을 되돌려 둔다
                if dst.exists() and not f.exists():
                    dst.replace(f)
            raise
        if prev and prev[0][0] == out:
            prev[0][1].replace(out.with_suffix(".old.json"))
        out.write_text(json.dumps(a, ensure_ascii=False, indent=1))
        self.log(job, f"분석을 합쳤어요 ({time.time() - started:.0f}초, ${sum(costs):.2f})")
        # 번역투 롤 용어(플렉스, 리치, R...)를 한국 롤 유저가 쓰는 말로 한 번 더 고친다. 실패해도 분석은 살린다
        try:
            await self._exec(job, [PY, "tools/terms.py", str(gdir), "--fix"])
        except RuntimeError:
            self.log(job, "용어 검사에서 직접 고쳐야 할 표현이 남았어요 (위 목록)")
        return json.loads(out.read_text())

    async def _update_kb(self, job: Job) -> None:
        """분석에서 판을 넘는 지식(개념, 원칙, 복습 퀴즈)을 kb에 쌓는다. 분석 화면은 이미 볼 수 있다"""
        target = VODS / job.vod / f"game{job.game}"
        prompt = (
            f"`.claude/skills/jungle-vod/SKILL.md`와 `SCHEMA.md`를 읽고, 'D. 나눠서 분석하기'의 '지식 정리 담당'을 `{target}`에 대해 수행해. "
            f"분석은 `{target}/analysis.json`(new_concepts, new_rules, new_quizzes만 고쳐), "
            f"갱신할 파일은 `{KB}/concepts.json`, `{KB}/rules.json`, `{KB}/quizzes.json`이야. "
            f"이미지 경로는 `{VODS}` 기준 상대 경로로 써. 사용자에게 질문하지 말고 끝까지 진행해. 마지막 답변은 한 줄로."
        )
        await self._claude(job, prompt, tag="지식 정리")
        json.loads((target / "analysis.json").read_text())

    async def _analyze_mine(self, job: Job) -> None:
        from . import db  # 사용자 데이터는 db에
        root = VODS / job.vod
        target = root / "game1"
        gid = root.name
        goal = db.q("SELECT g.* FROM goals g JOIN my_games m ON m.goal_id = g.id WHERE m.id = ?", (gid,))
        user = db.q("SELECT u.* FROM users u JOIN my_games m ON m.user_id = u.id WHERE m.id = ?", (gid,))
        tier = (user[0].get("tier") if user else None) or "모름"
        extra = (f"게임 기록은 `{root}/live.json`. 플레이어 티어: {tier}. "
                 + (f"이 판 전에 플레이어가 정한 목표: \"{goal[0]['text']}\" (흐름 담당이 goal_check에 판정). " if goal
                    else "이 판은 정한 목표가 없어(흐름 담당은 goal_check를 빼고 next_goal만). "))
        a = await self._analyze_parallel(job, target, "mine", extra)
        ng = a.get("next_goal") or {}
        job.summary = (f"다음 목표: {ng.get('when')} → {ng.get('then')}" if ng else "") or job.summary
        # 목표 실천 여부: 사용자가 직접 고르지 않았으면 분석 판정을 넣는다
        gc = a.get("goal_check") or {}
        if goal and gc.get("followed") in ("yes", "partial", "no", "na") and not goal[0].get("followed"):
            db.x("UPDATE goals SET followed = ?, note = ? WHERE id = ?", (gc["followed"], gc.get("evidence"), goal[0]["id"]))

    async def _coach(self, job: Job) -> None:
        """판 전체 총평: 분석, 내가 먼저 한 복기, 가까운 프로 판, 지난 복기 노트를 보고 쓴다. 결과의 lessons는 복기 노트에 쌓인다"""
        from . import db, debrief
        root = VODS / job.vod
        gdir = root / "game1"
        gid = root.name
        rows = db.q("SELECT user_id FROM my_games WHERE id = ?", (gid,))
        uid = rows[0]["user_id"] if rows else "local"
        # 본인 복기와 비교하려고, 아직 복기 시간인데 안 했으면 조금(최대 2분) 기다린다
        for i in range(24):
            d = debrief.get_row(uid, gid)
            if not d or d.get("self") or (d.get("lock_until") or 0) < time.time():
                break
            if i == 0:
                self.log(job, "내 복기를 기다려요 (최대 2분)")
            if job.id in self.cancelled:
                raise RuntimeError("취소됨")
            await asyncio.sleep(5)
        ctx = debrief.coach_context(uid, gid, gdir)
        part = gdir / "parts" / "coach.json"
        prompt = (
            f"`.claude/skills/jungle-vod/SKILL.md`와 `SCHEMA.md`를 읽고, 'D. 나눠서 분석하기'의 '총평 담당'을 `{gdir}`에 대해 수행해. "
            f"분석은 `{gdir}/analysis.json`, 총평 재료(내 복기, 지난 복기 노트, 가까운 프로 판, 원칙)는 `{ctx}`. "
            f"결과는 `{part}`에 coach, next_goal 키만 담은 JSON 객체로 써. analysis.json과 kb/는 쓰지 마. "
            "사용자에게 질문하지 말고 끝까지 진행해. 마지막 답변은 한국어 한 줄로."
        )
        for attempt in (1, 2):
            part.unlink(missing_ok=True)
            try:
                await self._claude(job, prompt, tag="총평", effort=analysis_effort())
                data = json.loads(part.read_text())
                if not isinstance(data.get("coach"), dict):
                    raise ValueError("coach.json에 coach가 없어요")
                break
            except Exception as e:  # noqa: BLE001
                if job.id in self.cancelled or attempt == 2:
                    raise
                self.log(job, f"[총평] 다시 시도해요: {e}")
        out = gdir / "analysis.json"
        a = json.loads(out.read_text())
        a["coach"] = data["coach"]
        if isinstance(data.get("next_goal"), dict) and data["next_goal"].get("when"):
            a["next_goal"] = data["next_goal"]
        out.write_text(json.dumps(a, ensure_ascii=False, indent=1))
        n = debrief.ingest(uid, gid, data["coach"])
        self.log(job, f"복기 노트에 {n}개를 쌓았어요")
        ng = a.get("next_goal") or {}
        job.summary = (data["coach"].get("headline") or "") + (f"\n다음 목표: {ng.get('when')} → {ng.get('then')}" if ng else "")
        try:
            await self._exec(job, [PY, "tools/terms.py", str(gdir), "--fix"])
        except RuntimeError:
            self.log(job, "용어 검사에서 직접 고쳐야 할 표현이 남았어요 (위 목록)")

    async def _claude(self, job: Job, prompt: str, tag: str = "", effort: str | None = None) -> dict:
        cmd = [*find_claude(), "-p", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
        if os.environ.get("JUNGLE_CLAUDE_MODEL"):
            cmd += ["--model", os.environ["JUNGLE_CLAUDE_MODEL"]]
        # 생각(thinking)에 쓰는 시간이 분석 시간의 대부분이라 노력 수준으로 조절한다
        if effort or os.environ.get("JUNGLE_CLAUDE_EFFORT"):
            cmd += ["--effort", effort or os.environ["JUNGLE_CLAUDE_EFFORT"]]
        state = {"result": None}
        pre = f"[{tag}] " if tag else ""

        def on_line(line: str) -> None:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                self.log(job, pre + line)
                return
            t = ev.get("type")
            if t == "assistant":
                for c in ev.get("message", {}).get("content", []):
                    if c.get("type") == "text" and c["text"].strip():
                        self.log(job, pre + "💬 " + c["text"].strip())
                    elif c.get("type") == "tool_use":
                        self.log(job, pre + "· " + describe_tool(c.get("name", ""), c.get("input", {})))
            elif t == "result":
                state["result"] = ev
                cost = ev.get("total_cost_usd")
                secs = (ev.get("duration_ms") or 0) / 1000
                self.log(job, pre + f"Claude 완료 ({secs:.0f}초" + (f", ${cost:.2f}" if cost else "") + ")")

        await self._exec(job, cmd, on_line, stdin_text=prompt)
        res = state["result"]
        if not res:
            raise RuntimeError("Claude가 결과 없이 끝났어요")
        if res.get("is_error"):
            raise RuntimeError(f"Claude 오류: {res.get('result')}")
        if not tag:
            job.summary = (res.get("result") or "").strip()[:2000]
        return res


def analysis_effort() -> str:
    """설정의 분석 방식 → Claude effort. 환경 변수 JUNGLE_CLAUDE_EFFORT가 있으면 그걸 쓴다"""
    if os.environ.get("JUNGLE_CLAUDE_EFFORT"):
        return os.environ["JUNGLE_CLAUDE_EFFORT"]
    try:
        from . import system  # system이 jobs를 불러서, 여기서는 쓸 때 불러온다
        return "medium" if system.settings().get("analysis") == "deep" else "low"
    except Exception:  # noqa: BLE001
        return "low"


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
