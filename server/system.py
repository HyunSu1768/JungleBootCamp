"""앱 정보, 기기 설정, Claude 연결(설치, 로그인), 녹화 에이전트 관리.

데스크톱 앱(JUNGLE_DESKTOP=1)에서는 서버가 녹화 에이전트를 직접 띄우고 지킨다.
게임하는 PC = 앱을 켠 PC라서 녹화 파일은 올리지 않고 경로만 넘긴다(--local).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import db, platform_util
from .jobs import ROOT, VODS

router = APIRouter()
DESKTOP = os.environ.get("JUNGLE_DESKTOP") == "1"
DATA = db.DB_PATH.parent
SETTINGS = DATA / "settings.json"
# analysis: fast(빠르게, Claude effort low) | deep(꼼꼼하게, medium). 분석 시간 대부분이 Claude가 생각하는 시간이라 이걸로 조절한다
DEFAULTS = {"recording": True, "screen": "0", "audio": None, "onboarded": False, "analysis": "fast"}


# ================= 앱, 설정 =================
def settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)


@router.get("/api/app")
def app_info():
    return {"version": os.environ.get("JUNGLE_APP_VERSION", "dev"), "desktop": DESKTOP,
            "platform": "windows" if platform_util.WINDOWS else "mac" if platform_util.MAC else "linux",
            "data_dir": str(DATA), "settings": settings(), "recorder": recorder.state()}


@router.post("/api/app/shutdown")
def app_shutdown(request: Request):
    """데스크톱 앱이 끝나기 전에 부른다: 녹화 중이던 판을 마무리한다"""
    if request.client and request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403)
    shutdown()
    return {"ok": True}


@router.put("/api/settings")
def put_settings(body: dict):
    cur = settings()
    for k in DEFAULTS:
        if k in body:
            cur[k] = body[k]
    DATA.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(cur, ensure_ascii=False))
    if DESKTOP:
        recorder.apply()
    return cur


# ================= Claude 연결 =================
def _run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=platform_util.claude_env(),
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, str(e)


class _Task:
    """설치, 로그인처럼 오래 걸리는 작업 하나의 상태"""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.log: list[str] = []
        self.running = False
        self.error: str | None = None
        self.url: str | None = None
        self.started = 0.0

    def view(self) -> dict:
        return {"running": self.running, "error": self.error, "url": self.url, "log": self.log[-12:]}


install_task, login_task = _Task(), _Task()
_status_cache: dict = {"at": 0.0, "v": None}


@router.get("/api/claude")
def claude_status(fresh: bool = False):
    if not fresh and _status_cache["v"] and time.time() - _status_cache["at"] < 4:
        v = dict(_status_cache["v"])
    else:
        cmd = platform_util.find_claude()
        v = {"installed": bool(cmd), "path": cmd[-1] if cmd else None, "version": None,
             "logged_in": False, "auth_method": None, "email": None,
             "git_bash": platform_util.git_bash() if platform_util.WINDOWS else None}
        if cmd:
            code, out = _run([*cmd, "--version"])
            v["version"] = out.strip().splitlines()[0] if code == 0 and out.strip() else None
            code, out = _run([*cmd, "auth", "status", "--json"])
            try:
                st = json.loads(out[out.index("{"):out.rindex("}") + 1])
            except ValueError:
                st = {}
            # 문서상 로그인 여부는 종료 코드(0 = 로그인)가 기준이다
            v["logged_in"] = code == 0 and st.get("authMethod", "none") != "none"
            v["auth_method"] = st.get("authMethod")
            v["email"] = st.get("email")
        _status_cache.update(at=time.time(), v=v)
    v["install"] = install_task.view()
    v["login"] = login_task.view()
    v["platform"] = "windows" if platform_util.WINDOWS else "mac" if platform_util.MAC else "linux"
    return v


def _pump(task: _Task, proc: subprocess.Popen, on_done=None) -> None:
    assert proc.stdout
    for raw in iter(proc.stdout.readline, ""):
        line = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", raw).strip()  # 색, 커서 제어 문자 제거
        if not line:
            continue
        task.log.append(line[:300])
        m = re.search(r"https://\S+", line)
        if m and not task.url and ("oauth" in m.group(0) or "claude.ai" in m.group(0) or "anthropic" in m.group(0)):
            task.url = m.group(0).rstrip(".,)")
    code = proc.wait()
    task.running = False
    if code != 0 and not task.error:
        task.error = f"종료 코드 {code}"
    _status_cache["at"] = 0
    if on_done:
        on_done(code)


@router.post("/api/claude/install")
def claude_install():
    if install_task.running:
        return install_task.view()
    if platform_util.WINDOWS:
        # 공식 설치 스크립트. 관리자 권한이 필요 없고 %USERPROFILE%\.local\bin\claude.exe에 설치된다
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://claude.ai/install.ps1 | iex"]
    else:
        cmd = ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"]
    install_task.__init__()
    install_task.running, install_task.started = True, time.time()
    install_task.log.append("Claude Code를 내려받아 설치하고 있어요. 1~3분 걸려요.")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace")
    install_task.proc = proc
    threading.Thread(target=_pump, args=(install_task, proc), daemon=True).start()
    return install_task.view()


@router.post("/api/claude/login")
def claude_login():
    cmd = platform_util.find_claude()
    if not cmd:
        raise HTTPException(400, "Claude Code를 먼저 설치해 주세요")
    if login_task.running:
        return login_task.view()
    login_task.__init__()
    login_task.running, login_task.started = True, time.time()
    # 브라우저가 열리고 로그인하면 localhost로 돌아와 끝난다. 브라우저가 코드를 보여 주면 /api/claude/login/code로 넣는다
    proc = subprocess.Popen([*cmd, "auth", "login"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=platform_util.claude_env())
    login_task.proc = proc

    def done(code: int) -> None:
        # 터미널이 없어서 로그인 화면을 못 띄웠으면(빨리 실패) 로그인 창을 직접 연다. 사용자가 누른 때만 보이는 창
        if code != 0 and time.time() - login_task.started < 8:
            login_task.error = None
            login_task.log.append("로그인 창을 따로 열었어요. 창의 안내를 따라 로그인해 주세요.")
            open_login_window(cmd)

    threading.Thread(target=_pump, args=(login_task, proc, done), daemon=True).start()
    return login_task.view()


def open_login_window(cmd: list[str]) -> None:
    if platform_util.WINDOWS:
        subprocess.Popen(["cmd", "/c", "start", "Claude 로그인", *cmd, "auth", "login"], creationflags=platform_util.NO_WINDOW)
    elif platform_util.MAC:
        line = " ".join(f"'{c}'" for c in cmd) + " auth login"
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{line}"', "-e", 'tell application "Terminal" to activate'])


class Code(BaseModel):
    code: str


@router.post("/api/claude/login/code")
def claude_login_code(body: Code):
    p = login_task.proc
    if not p or p.poll() is not None or not p.stdin:
        raise HTTPException(400, "진행 중인 로그인이 없어요. 다시 눌러 주세요")
    p.stdin.write(body.code.strip() + "\n")
    p.stdin.flush()
    return login_task.view()


@router.post("/api/claude/login/window")
def claude_login_window():
    cmd = platform_util.find_claude()
    if not cmd:
        raise HTTPException(400, "Claude Code를 먼저 설치해 주세요")
    if login_task.proc and login_task.proc.poll() is None:
        platform_util.kill_tree(login_task.proc.pid, force=True)
    open_login_window(cmd)
    return {"ok": True}


# ================= 녹화 에이전트 (데스크톱) =================
class Recorder:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.stop_file = DATA / "recorder.stop"
        self.token: str | None = None
        self.started = 0.0
        self.fails = 0
        self._lock = threading.Lock()

    def state(self) -> dict:
        return {"managed": DESKTOP, "running": bool(self.proc and self.proc.poll() is None), "fails": self.fails}

    def _token(self) -> str:
        if not self.token:
            self.token = secrets.token_urlsafe(24)
            from .mine import _hash
            uid = "local"
            if not db.q("SELECT 1 FROM users WHERE id = ?", (uid,)):
                db.x("INSERT INTO users (id, created) VALUES (?, ?)", (uid, db.now()))
            db.x("DELETE FROM agent_tokens WHERE user_id = ? AND label = ?", (uid, "이 PC (앱 내장)"))
            db.x("INSERT INTO agent_tokens (hash, user_id, label, created) VALUES (?, ?, ?, ?)",
                 (_hash(self.token), uid, "이 PC (앱 내장)", db.now()))
        return self.token

    def start(self) -> None:
        s = settings()
        port = os.environ.get("JUNGLE_PORT", "8790")
        out = DATA / "recordings"
        self.stop_file = DATA / "recorder.stop"
        self.stop_file.unlink(missing_ok=True)
        cmd = [sys.executable, str(ROOT / "agent" / "recorder.py"), "--local", "--server", f"http://127.0.0.1:{port}",
               "--token", self._token(), "--screen", str(s.get("screen") or "0"), "--out", str(out),
               "--stop-file", str(self.stop_file)]
        if s.get("audio"):
            cmd += ["--audio", s["audio"]]
        (VODS / "_logs").mkdir(parents=True, exist_ok=True)
        log = (VODS / "_logs" / "recorder.log").open("a", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=ROOT,
                                     env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
        self.started = time.time()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            # 멈춤 파일을 만들면 에이전트가 녹화 중이던 판을 마무리(파일 닫기, 기록 저장, 서버에 넘기기)하고 끝난다
            self.stop_file.touch()
            try:
                self.proc.wait(timeout=25)
            except subprocess.TimeoutExpired:
                platform_util.kill_tree(self.proc.pid, force=True)
        self.proc = None

    def apply(self) -> None:
        """설정에 맞게 켜고 끈다. 화면 번호 등이 바뀌면 다시 띄운다"""
        with self._lock:
            self.stop()
            if settings().get("recording"):
                self.start()

    def watch(self) -> None:
        """죽으면 다시 띄운다 (연속으로 죽으면 간격을 늘린다)"""
        while True:
            time.sleep(10)
            with self._lock:
                if not settings().get("recording") or (self.proc and self.proc.poll() is None):
                    continue
                if self.proc is not None:
                    self.fails += 1
                    if time.time() - self.started < 60 * min(self.fails, 10):
                        continue
                self.start()


recorder = Recorder()


def startup() -> None:
    if DESKTOP:
        recorder.apply()
        threading.Thread(target=recorder.watch, daemon=True).start()


def shutdown() -> None:
    if DESKTOP:
        recorder.stop()
