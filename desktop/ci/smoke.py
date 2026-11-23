"""CI(Windows)에서 앱 백엔드가 제대로 도는지 확인한다. 실패하면 릴리스를 만들지 않는다."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ.update(JUNGLE_VODS=str(tmp / "vods"), JUNGLE_KB=str(ROOT / "kb"), JUNGLE_DB=str(tmp / "app.db"))


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("OK   " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        sys.exit(1)


# 1. 서버가 뜨고 주요 API가 응답한다
from fastapi.testclient import TestClient  # noqa: E402

import server.app  # noqa: E402

with TestClient(server.app.app) as c:
    for path in ("/api/app", "/api/me", "/api/train/overview", "/api/mine", "/api/goals", "/api/agent", "/api/kb", "/api/vods",
                 "/api/debrief/active", "/api/lessons", "/api/growth", "/api/overlay"):
        r = c.get(path)
        check(f"GET {path}", r.status_code == 200, str(r.status_code))
    r = c.get("/api/claude", params={"fresh": True})
    check("GET /api/claude", r.status_code == 200, str(r.json().get("installed")))

# 2. 하위 프로세스가 숨긴 콘솔로 뜨고 출력도 받는다
from server import platform_util  # noqa: E402

platform_util.hide_console_windows()
if platform_util.WINDOWS:
    out = subprocess.run(["cmd", "/c", "echo", "hidden-ok"], capture_output=True, text=True).stdout
    check("숨긴 콘솔에서 실행, 출력 받기", "hidden-ok" in out, out.strip())
    # 손자 프로세스도 같은 콘솔을 물려받아 출력이 이어진다
    out = subprocess.run(["cmd", "/c", "cmd /c echo grandchild-ok"], capture_output=True, text=True).stdout
    check("손자 프로세스", "grandchild-ok" in out, out.strip())

# 3. ffmpeg(앱에 들어가는 것) + 프레임 시각 글꼴 경로
sys.path.insert(0, str(ROOT / "tools"))
from common import FONT, drawtext_clock  # noqa: E402

ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
out_img = tmp / "clock.jpg"
p = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:duration=1",
                    "-vf", drawtext_clock(0, 20), "-frames:v", "1", str(out_img)], capture_output=True, text=True)
check(f"ffmpeg drawtext ({FONT})", p.returncode == 0 and out_img.exists(), p.stderr[-300:])
enc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
check("ffmpeg 그래픽카드 인코더 포함", all(e in enc for e in ("h264_nvenc", "h264_amf", "h264_qsv")))
filt = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
check("ffmpeg ddagrab 포함", "ddagrab" in filt)

# 4. 녹화 에이전트 명령 후보
sys.path.insert(0, str(ROOT / "agent"))
import recorder  # noqa: E402

cmds = recorder.capture_cmds(tmp / "o.mkv", "0", None, 30, 1080, "6M")
check("녹화 명령 후보", len(cmds) >= 2, f"{len(cmds)}개")

# 5. 미니맵 상대 등장 찾기 (OpenCV)
import numpy as np  # noqa: E402

import sightings  # noqa: E402

img = np.zeros((sightings.SIZE, sightings.SIZE, 3), np.uint8)
import cv2  # noqa: E402

cv2.circle(img, (120, 140), 12, (0, 0, 255), 2)  # 빨간 테두리 아이콘 하나
found = sightings.enemies(img)
check("미니맵 상대 아이콘 찾기", len(found) == 1, str(found))

# 6. 복기 시간: 가짜 롤 클라이언트(LCU)에서 큐를 돌리면 에이전트가 취소한다
import json as _json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

calls: list[str] = []
phase = {"v": "Matchmaking"}


class FakeLCU(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes = b"") -> None:
        self.send_response(200 if body else 204)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(_json.dumps(phase["v"]).encode())

    def do_DELETE(self):
        calls.append(self.path)
        phase["v"] = "Lobby"
        self._send()

    do_POST = do_DELETE


lcu_srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLCU)
threading.Thread(target=lcu_srv.serve_forever, daemon=True).start()
lock = Path(tempfile.mkdtemp()) / "lockfile"
lock.write_text(f"LeagueClient:1:{lcu_srv.server_port}:pw:http")
lc = recorder.LeagueClient(str(lock))
check("복기 시간 큐 취소", lc.stop_queue() == "Matchmaking" and calls == ["/lol-lobby/v2/lobby/matchmaking/search"], str(calls))
phase["v"] = "ChampSelect"
check("챔피언 선택은 건드리지 않음", lc.stop_queue() is None and len(calls) == 1, str(calls))
lcu_srv.shutdown()

# 7. 받아쓰기 라이브러리
import importlib.util  # noqa: E402

check("faster-whisper", bool(importlib.util.find_spec("faster_whisper")) or not platform_util.WINDOWS)
check("yt-dlp", bool(importlib.util.find_spec("yt_dlp")))
print("모두 통과")
