"""OS별 차이를 한곳에. 특히 Windows에서 하위 프로세스가 콘솔 창을 띄우지 않게 한다.

데스크톱 앱(Electron)은 창이 없는 GUI 프로세스라, 거기서 띄운 콘솔 프로그램(python, ffmpeg, claude, git bash)은
따로 지정하지 않으면 매번 검은 터미널 창을 연다. 모든 subprocess에 CREATE_NO_WINDOW를 붙여 막는다.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def hide_console_windows() -> None:
    """이 프로세스에서 띄우는 모든 subprocess(asyncio 포함)를 '숨겨진 콘솔'에서 실행한다.

    CREATE_NO_WINDOW만 쓰면 자식이 콘솔을 아예 못 가져서, 자식이 또 띄우는 프로세스(claude의 Bash, PowerShell 도구,
    yt-dlp의 ffmpeg)마다 Windows가 새 콘솔 창을 만든다. 숨긴 콘솔을 하나 주면 손자들은 그 콘솔을 물려받아 창이 안 뜬다.
    """
    if not WINDOWS or getattr(subprocess.Popen, "_hidden_console", False):
        return
    orig = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            si = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        orig(self, *args, **kwargs)

    subprocess.Popen.__init__ = init  # type: ignore[method-assign]
    subprocess.Popen._hidden_console = True  # type: ignore[attr-defined]


def kill_tree(pid: int, force: bool = False) -> None:
    """프로세스와 그 자식(ffmpeg, claude가 띄운 셸 등)까지 끈다"""
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
        else:
            os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def find_claude() -> list[str] | None:
    """claude CLI 실행 명령. Windows에선 .cmd(npm 설치)를 피하고 claude.exe나 node + cli.js를 직접 부른다
    (.cmd를 거치면 cmd.exe가 인자를 망가뜨리고 콘솔 창이 뜨기 쉽다)"""
    home = Path.home()
    cands = [os.environ.get("JUNGLE_CLAUDE"), shutil.which("claude")]
    if WINDOWS:
        cands += [str(home / ".local" / "bin" / "claude.exe"),
                  str(Path(os.environ.get("LOCALAPPDATA", home)) / "Programs" / "claude" / "claude.exe"),
                  str(Path(os.environ.get("APPDATA", home)) / "npm" / "claude.cmd")]
    else:
        cands += [str(home / ".local" / "bin" / "claude"), str(home / ".claude" / "local" / "claude")]
    for c in cands:
        if not c or not Path(c).exists():
            continue
        if WINDOWS and c.lower().endswith((".cmd", ".bat")):
            cli = Path(c).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
            node = shutil.which("node")
            if cli.exists() and node:
                return [node, str(cli)]
            continue
        return [c]
    return None


def git_bash() -> str | None:
    """Windows의 Claude Code는 Git Bash로 명령을 실행한다"""
    if not WINDOWS:
        return "/bin/bash"
    env = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if env and Path(env).exists():
        return env
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                 str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")):
        p = Path(base) / "Git" / "bin" / "bash.exe"
        if base and p.exists():
            return str(p)
    git = shutil.which("git")
    if git:
        p = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if p.exists():
            return str(p)
    return None


def claude_env() -> dict:
    """headless claude 실행용 환경. 자동 업데이트 확인 등으로 멈추지 않게 한다"""
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "DISABLE_AUTOUPDATER": "1"}
    # -p 모드에선 ANTHROPIC_API_KEY가 있으면 구독 대신 API 과금이 된다. 앱은 로그인한 구독을 쓴다
    if not env.get("JUNGLE_USE_API_KEY"):
        env.pop("ANTHROPIC_API_KEY", None)
    if WINDOWS and not env.get("CLAUDE_CODE_GIT_BASH_PATH"):
        bash = git_bash()
        if bash:
            env["CLAUDE_CODE_GIT_BASH_PATH"] = bash
    return env
