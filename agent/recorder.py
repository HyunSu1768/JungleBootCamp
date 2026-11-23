#!/usr/bin/env python3
"""정글러훈련소 녹화 에이전트: 롤 게임이 시작되면 알아서 화면을 녹화하고, 끝나면 서버에 넘긴다.

게임 감지는 롤 클라이언트가 게임 중에만 여는 공식 로컬 API(Live Client Data, https://127.0.0.1:2999)로 한다.
게임 메모리를 읽지 않는다. 같은 API로 인게임 시계, 이벤트(킬, 오브젝트), 10초마다 점수(CS, KDA, 레벨, 아이템)를 같이 남긴다.

판이 끝나면 서버가 복기 시간(기본 10분)을 정해 준다. 그동안 롤 클라이언트의 로컬 API(LCU, lockfile의 포트와 비밀번호)로
큐 상태만 보고, 큐를 돌리면 취소한다(수락 창이 떴으면 거절). 챔피언 선택 중에는 건드리지 않는다(닷지 불이익).

    python agent/recorder.py --server http://<서버 주소>:8790 --token <웹에서 받은 연결 토큰>
    python agent/recorder.py --list-screens        # 녹화할 화면 번호 확인

기본은 녹화 파일을 서버로 이어 올리기(끊겨도 이어서) 한다. 서버와 같은 PC면 --local로 경로만 넘긴다.
Windows: ffmpeg 6 이상 필요 (winget install Gyan.FFmpeg). 롤은 '테두리 없음' 창 모드를 권장한다.

표준 라이브러리와 ffmpeg만 쓴다. 나중에 데스크톱 앱(Tauri, Electron)으로 감쌀 때 이 파일을 그대로 띄우면 된다.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import re
import shutil
import signal
import ssl
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Windows: ffmpeg를 숨긴 콘솔에서 띄워 창이 뜨지 않게 (앱에 들어 있으면 서버와 같은 코드를 쓴다)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from server.platform_util import hide_console_windows
except ImportError:
    def hide_console_windows() -> None:
        if os.name != "nt":
            return
        orig = subprocess.Popen.__init__

        def init(self, *a, **kw):
            if not kw.get("creationflags"):
                kw["creationflags"] = subprocess.CREATE_NEW_CONSOLE
                si = kw.get("startupinfo") or subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                kw["startupinfo"] = si
            orig(self, *a, **kw)
        subprocess.Popen.__init__ = init
hide_console_windows()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 콘솔에서 한글 로그

VERSION = "0.2.0"
CHUNK = 16 << 20    # 업로드 조각 16MB
SSL = ssl.create_default_context()
SSL.check_hostname = False
SSL.verify_mode = ssl.CERT_NONE  # 롤 클라이언트는 자체 서명 인증서를 쓴다

POLL = 2.0          # 게임 감지 간격
SNAPSHOT = 10.0     # 점수 기록 간격
GONE_AFTER = 12.0   # API가 이만큼 응답 없으면 게임이 끝난 걸로 본다
TAIL = 4.0          # GameEnd 뒤 조금 더 녹화 (승패 화면)
MODES = {"CLASSIC"}  # 소환사의 협곡만. 연습 모드(PRACTICETOOL), 칼바람(ARAM)은 녹화 안 함


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


# ---------------- 롤 Live Client Data API ----------------
class LiveClient:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def get(self, path: str):
        try:
            with urllib.request.urlopen(f"{self.base}/liveclientdata/{path}", timeout=1.5, context=SSL) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, OSError):
            return None


def trim_players(players: list[dict]) -> list[dict]:
    out = []
    for p in players or []:
        out.append({
            "champion": p.get("championName"), "riot_id": p.get("riotId") or p.get("summonerName"),
            "team": p.get("team"), "position": p.get("position") or None, "level": p.get("level"),
            "dead": p.get("isDead"), "respawn": round(p.get("respawnTimer") or 0, 1),
            "scores": p.get("scores"), "items": [i.get("itemID") for i in p.get("items") or []],
            "spells": [(p.get("summonerSpells") or {}).get(k, {}).get("displayName") for k in ("summonerSpellOne", "summonerSpellTwo")],
        })
    return out


# ---------------- 롤 클라이언트 (LCU): 복기 시간 동안 큐 막기 ----------------
def _lockfile_candidates(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit)]
    if platform.system() == "Windows":
        return [Path(f"{d}:/Riot Games/League of Legends/lockfile") for d in "CDEFG"]
    if platform.system() == "Darwin":
        return [Path("/Applications/League of Legends.app/Contents/LoL/lockfile")]
    return []


class LeagueClient:
    """롤 클라이언트가 켜질 때 만드는 lockfile(이름:pid:포트:비밀번호:프로토콜)로 로컬 API에 붙는다.
    설치 폴더가 기본 위치가 아니면 실행 중인 LeagueClientUx.exe의 명령줄에서 포트와 비밀번호를 읽는다."""

    def __init__(self, lockfile: str | None = None) -> None:
        self.lockfile = lockfile
        self.base: str | None = None
        self.auth = ""
        self._ps_at = 0.0

    def _connect(self) -> bool:
        for f in _lockfile_candidates(self.lockfile):
            try:
                _, _, port, pw, proto = f.read_text().strip().split(":")[:5]
            except (OSError, ValueError):
                continue
            self.base, self.auth = f"{proto}://127.0.0.1:{port}", pw
            return True
        if platform.system() == "Windows" and not self.lockfile and time.monotonic() - self._ps_at > 15:
            self._ps_at = time.monotonic()
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\").CommandLine"],
                    capture_output=True, text=True, timeout=10).stdout
            except (OSError, subprocess.TimeoutExpired):
                out = ""
            port, pw = re.search(r"--app-port=(\d+)", out), re.search(r"--remoting-auth-token=([\w-]+)", out)
            if port and pw:
                self.base, self.auth = f"https://127.0.0.1:{port.group(1)}", pw.group(1)
                return True
        return False

    def _req(self, method: str, path: str):
        if not self.base and not self._connect():
            return None
        req = urllib.request.Request(self.base + path, method=method, data=b"" if method in ("POST", "DELETE") else None)
        req.add_header("Authorization", "Basic " + base64.b64encode(f"riot:{self.auth}".encode()).decode())
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=2, context=SSL if self.base.startswith("https") else None) as r:
                body = r.read()
                return json.loads(body) if body else True
        except urllib.error.HTTPError:
            return False  # 클라이언트는 떠 있는데 그 요청이 안 됨 (큐가 이미 없음 등)
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, OSError):
            self.base = None  # 클라이언트가 꺼졌거나 다시 켜졌다(포트가 바뀜). 다음에 다시 찾는다
            return None

    def phase(self) -> str | None:
        """None(클라이언트 없음) | Lobby | Matchmaking | ReadyCheck | ChampSelect | InProgress | EndOfGame ..."""
        p = self._req("GET", "/lol-gameflow/v1/gameflow-phase")
        return p if isinstance(p, str) else None

    def stop_queue(self) -> str | None:
        """큐를 돌리고 있으면 취소한다. 막았으면 그때의 단계를 돌려준다"""
        ph = self.phase()
        if ph == "ReadyCheck":
            self._req("POST", "/lol-matchmaking/v1/ready-check/decline")
            self._req("DELETE", "/lol-lobby/v2/lobby/matchmaking/search")
            return ph
        if ph == "Matchmaking":
            self._req("DELETE", "/lol-lobby/v2/lobby/matchmaking/search")
            return ph
        return None


# ---------------- 화면 녹화 (ffmpeg) ----------------
def encoders() -> set[str]:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except OSError:
        return set()
    return {line.split()[1] for line in out.splitlines() if line.startswith(" V")}


def capture_cmds(out: Path, screen: str, audio: str | None, fps: int, height: int, bitrate: str) -> list[list[str]]:
    """녹화 명령 후보. 앞에서부터 시도하고, 몇 초 안에 죽으면 다음 것으로 (PC마다 ffmpeg 버전, 드라이버가 달라서)"""
    system = platform.system()
    enc = encoders()
    tail = ["-g", str(fps * 2), "-c:a", "aac", "-b:a", "128k", str(out)]  # mkv: 녹화 중 꺼져도 앞부분은 산다
    cpu_scale = ["-vf", f"scale=-2:'min({height},ih)'"]
    x264 = ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-b:v", bitrate]  # 게임 중 CPU 부담이 커서 마지막 수단
    head = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    cands: list[list[str]] = []
    if system == "Darwin":
        src = ["-f", "avfoundation", "-capture_cursor", "1", "-framerate", str(fps), "-pixel_format", "nv12",
               "-i", f"Capture screen {screen}:{audio if audio is not None else 'none'}"]
        if "h264_videotoolbox" in enc:
            cands.append([*head, *src, *cpu_scale, "-r", str(fps), "-c:v", "h264_videotoolbox", "-b:v", bitrate, "-realtime", "1", *tail])
        cands.append([*head, *src, *cpu_scale, "-r", str(fps), *x264, *tail])
    elif system == "Windows":
        # Desktop Duplication(ddagrab): 화면을 GPU 메모리에서 바로 가져온다. gdigrab보다 훨씬 가볍다
        grab = f"ddagrab=output_idx={screen}:framerate={fps}:draw_mouse=1"
        aud = ["-f", "dshow", "-i", f"audio={audio}"] if audio else []  # 스테레오 믹스, VoiceMeeter 같은 장치 이름
        gpu = {
            "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-rc", "cbr", "-b:v", bitrate],
            "h264_amf": ["-c:v", "h264_amf", "-usage", "lowlatency", "-rc", "cbr", "-b:v", bitrate],
            "h264_qsv": ["-c:v", "h264_qsv", "-preset", "veryfast", "-b:v", bitrate],
        }
        for name in ("h264_nvenc", "h264_amf"):
            if name in enc:
                # GPU 프레임을 인코더에 그대로 넘긴다. 크기 조절도 GPU에서(ffmpeg 8+), 안 되면 원본 해상도로
                cands.append([*head, "-f", "lavfi", "-i", grab, *aud, "-vf", f"scale_d3d11=-2:{height}", *gpu[name], *tail])
                cands.append([*head, "-f", "lavfi", "-i", grab, *aud, *gpu[name], *tail])
        for name in ("h264_nvenc", "h264_amf", "h264_qsv"):
            if name in enc:
                cands.append([*head, "-f", "lavfi", "-i", f"{grab},hwdownload,format=bgra", *aud, *cpu_scale, *gpu[name], *tail])
        cands.append([*head, "-f", "lavfi", "-i", f"{grab},hwdownload,format=bgra", *aud, *cpu_scale, *x264, *tail])
        cands.append([*head, "-f", "gdigrab", "-framerate", str(fps), "-i", "desktop", *aud, *cpu_scale, *x264, *tail])
    else:
        cands.append([*head, "-f", "x11grab", "-framerate", str(fps), "-i", os.environ.get("DISPLAY", ":0"), *cpu_scale, *x264, *tail])
    return cands


class Recording:
    def __init__(self, out_dir: Path, args) -> None:
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.dir = out_dir / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.video = self.dir / "recording.mkv"
        self.args = args
        self.proc: subprocess.Popen | None = None
        self.t0 = 0.0
        self.sync: list[float] = []        # 녹화 초 - 인게임 초
        self.events: dict[int, dict] = {}
        self.snapshots: list[dict] = []
        self.meta: dict = {"id": self.id, "agent": VERSION, "platform": platform.system(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.ended_at: float | None = None
        self.last_snapshot = 0.0

    def start(self) -> None:
        for cmd in capture_cmds(self.video, self.args.screen, self.args.audio, self.args.fps, self.args.height, self.args.bitrate):
            log("녹화 시작: " + " ".join(cmd[5:]))
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            self.t0 = time.monotonic()
            try:
                self.proc.wait(timeout=3)  # 3초 안에 죽으면 이 방식은 안 되는 PC
            except subprocess.TimeoutExpired:
                return
            err = (self.proc.stderr.read() or b"").decode(errors="replace").strip()
            log("이 방식으로는 녹화가 안 돼요. 다음 방식을 시도해요: " + err[-300:])
            self.video.unlink(missing_ok=True)
        log("녹화를 시작하지 못했어요. ffmpeg 버전(6 이상)과 화면 녹화 권한을 확인해 주세요")

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if not self.proc:
            return
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"q")  # ffmpeg를 깔끔하게 끝내야 파일 끝이 온전하다
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.send_signal(signal.SIGINT)
                self.proc.wait(timeout=10)
        err = (self.proc.stderr.read() or b"").decode(errors="replace").strip() if self.proc.stderr else ""
        if err:
            log("ffmpeg: " + err[-500:])
        self.meta["duration"] = round(self.elapsed(), 1)

    def observe(self, live: LiveClient, stats: dict) -> None:
        gt = stats.get("gameTime")
        if gt is not None:
            self.sync.append(self.elapsed() - gt)
        for e in (live.get("eventdata") or {}).get("Events", []):
            if e.get("EventID") not in self.events:
                self.events[e["EventID"]] = e
                if e.get("EventName") == "GameEnd" and self.ended_at is None:
                    self.ended_at = time.monotonic()
                    self.meta["result"] = {"Win": "승", "Lose": "패"}.get(e.get("Result"), e.get("Result"))
                    log(f"게임 끝: {self.meta['result']}")
        if time.monotonic() - self.last_snapshot >= SNAPSHOT:
            self.last_snapshot = time.monotonic()
            data = live.get("allgamedata") or {}
            players = trim_players(data.get("allPlayers"))
            if players:
                self.snapshots.append({"t": round(gt or 0, 1), "players": players})
            ap = data.get("activePlayer") or {}
            if ap and "me" not in self.meta:
                me_id = ap.get("riotId") or ap.get("summonerName")
                me = next((p for p in players if p["riot_id"] == me_id), None)
                self.meta["me"] = {"riot_id": me_id, **({k: me[k] for k in ("champion", "team", "position", "spells")} if me else {})}
                log(f"플레이어: {me_id} / {me and me['champion']} / {me and me['position']}")

    def finish(self) -> dict:
        offset = statistics.median(self.sync) if self.sync else None
        self.meta.update({
            "game_mode": self.meta.get("game_mode"),
            "offset": round(offset, 2) if offset is not None else None,  # 녹화 초 = 인게임 초 + offset
            "late_start": bool(offset is not None and offset < -15),        # 게임 도중에 녹화를 시작함 (감지 간격만큼은 늦어도 정상)
            "events": sorted(self.events.values(), key=lambda e: e.get("EventTime", 0)),
            "snapshots": self.snapshots,
        })
        (self.dir / "live.json").write_text(json.dumps(self.meta, ensure_ascii=False))
        return self.meta


# ---------------- 서버로 넘기기 ----------------
class Server:
    def __init__(self, base: str, token: str | None, local: bool) -> None:
        self.base, self.token, self.local = base.rstrip("/"), token, local

    def _req(self, method: str, path: str, body: bytes | None = None, ctype: str = "application/json", timeout: float = 5):
        req = urllib.request.Request(self.base + path, data=body, method=method)
        req.add_header("Content-Type", ctype)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=timeout, context=SSL if self.base.startswith("https") else None) as r:
            return json.loads(r.read() or b"null")

    def upload(self, rec_id: str, video: Path) -> None:
        """조각으로 이어 올리기. 서버가 받은 크기부터 다시 보낸다"""
        size = video.stat().st_size
        done = self._req("GET", f"/api/agent/uploads/{rec_id}")["size"]
        last_log = 0.0
        with video.open("rb") as f:
            while done < size:
                f.seek(done)
                chunk = f.read(CHUNK)
                done = self._req("PUT", f"/api/agent/uploads/{rec_id}?offset={done}&total={size}", chunk,
                                 "application/octet-stream", timeout=300)["size"]
                if time.monotonic() - last_log > 10:
                    last_log = time.monotonic()
                    log(f"올리는 중 {done * 100 // size}% ({done >> 20}/{size >> 20}MB)")

    def status(self, state: dict) -> dict | None:
        try:
            return self._req("POST", "/api/agent/status", json.dumps(state).encode(), timeout=2)
        except (urllib.error.URLError, OSError):
            return None  # 서버가 꺼져 있어도 녹화는 계속한다

    def blocked(self, phase: str) -> None:
        try:
            self._req("POST", "/api/agent/blocked", json.dumps({"phase": phase}).encode(), timeout=2)
        except (urllib.error.URLError, OSError):
            pass

    def deliver(self, rec_dir: Path) -> dict | None:
        meta = json.loads((rec_dir / "live.json").read_text())
        try:
            if self.local:
                body = {"path": str((rec_dir / "recording.mkv").resolve()), "meta": meta}
            else:
                self.upload(meta["id"], rec_dir / "recording.mkv")
                body = {"upload": meta["id"], "meta": meta}
            res = self._req("POST", "/api/agent/recordings", json.dumps(body).encode(), timeout=60)
            (rec_dir / "delivered").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))
            log(f"서버에 넘김: {rec_dir.name}")
            return res if isinstance(res, dict) else {}
        except (urllib.error.URLError, OSError) as e:
            log(f"서버에 넘기지 못했어요. 다음에 다시 시도해요: {e}")
            return None


def pending(out_dir: Path) -> list[Path]:
    return sorted(d for d in out_dir.glob("*/") if (d / "live.json").exists() and not (d / "delivered").exists()
                  and (d / "recording.mkv").exists())


def cleanup(out_dir: Path, keep: int, local: bool) -> None:
    """서버에 다 올린 녹화는 최근 keep개만 PC에 남긴다 (35분 판 하나가 1.5GB쯤). 같은 PC 모드는 서버가 파일을 가져가니 그대로"""
    if local:
        return
    done = sorted(d for d in out_dir.glob("*/") if (d / "delivered").exists())
    for d in done[:-keep] if keep > 0 else done:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 메인 루프 ----------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=os.environ.get("JUNGLE_SERVER", "http://127.0.0.1:8790"))
    ap.add_argument("--token", default=os.environ.get("JUNGLE_TOKEN"), help="웹 '내 게임'에서 받은 연결 토큰")
    ap.add_argument("--local", action="store_true", help="서버와 같은 PC면 올리지 않고 파일 경로만 넘긴다")
    ap.add_argument("--keep", type=int, default=10, help="서버에 넘긴 녹화를 PC에 최근 몇 개까지 남길지")
    ap.add_argument("--out", default=str(Path.home() / "Videos" / "JungleTrainer"), help="녹화 저장 폴더")
    ap.add_argument("--api", default="https://127.0.0.1:2999", help="롤 Live Client Data API 주소 (테스트용으로 바꿀 수 있다)")
    ap.add_argument("--screen", default="0", help="녹화할 화면 번호 (macOS). --list-screens로 확인")
    ap.add_argument("--audio", default=None, help="같이 녹음할 오디오 장치 (macOS: 번호, Windows: 장치 이름). 기본은 녹음 안 함")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--bitrate", default="6M")
    ap.add_argument("--all-modes", action="store_true", help="연습 모드, 칼바람도 녹화")
    ap.add_argument("--list-screens", action="store_true")
    ap.add_argument("--stop-file", help="이 파일이 생기면 녹화를 마무리하고 끝낸다 (앱이 에이전트를 끌 때)")
    ap.add_argument("--lcu-lockfile", default=os.environ.get("JUNGLE_LCU_LOCKFILE"),
                    help="롤 클라이언트 lockfile 위치 (기본: 설치 폴더를 찾거나 실행 중인 클라이언트에서 읽음)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg가 필요해요")
    if args.list_screens:
        if platform.system() == "Darwin":
            out = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                                 capture_output=True, text=True).stderr
            print("\n".join(line.split("] ", 1)[-1] for line in out.splitlines() if "Capture screen" in line or "audio devices" in line or ("] [" in line)))
        else:
            print("Windows, Linux는 주 화면 전체를 녹화해요")
        return

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.token:
        sys.exit("연결 토큰이 필요해요. 웹의 '내 게임 > 녹화 에이전트 연결'에서 복사해 --token으로 넣어 주세요")
    live, server = LiveClient(args.api), Server(args.server, args.token, args.local)
    lcu = LeagueClient(args.lcu_lockfile)
    lock_until = 0.0   # 복기 시간: 이때(epoch 초)까지 큐를 막는다. 서버가 정한다
    lcu_state: str | None = None  # 잠금 중 롤 클라이언트 연결 상태: ok | missing

    def take_lock(res: dict | None) -> None:
        nonlocal lock_until
        if isinstance(res, dict) and "lock_until" in res:
            new = float(res["lock_until"] or 0)
            if new > time.time() and new != lock_until:
                log(f"복기 시간: {int(new - time.time()) // 60}분 {int(new - time.time()) % 60}초 동안 큐를 막아요")
            lock_until = new

    rec: Recording | None = None
    last_seen = 0.0
    last_status = 0.0
    stopping = False
    give_up = False  # 이번 게임은 이미 녹화했거나 녹화에 실패했다. API가 사라질 때까지(게임을 나갈 때까지) 다시 시작하지 않는다

    def on_signal(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    log(f"녹화 에이전트 {VERSION} 시작. 롤 게임을 기다려요 (저장: {out_dir})")
    for d in pending(out_dir):
        server.deliver(d)

    while not stopping:
        if args.stop_file and Path(args.stop_file).exists():
            break
        stats = live.get("gamestats")
        now = time.monotonic()
        in_game = bool(stats) and stats.get("gameTime") is not None

        if in_game:
            last_seen = now
            mode = stats.get("gameMode")
            if rec is None and not give_up:
                me = live.get("activeplayer")
                if not me or "error" in me:  # 관전, 리플레이에는 내 챔피언이 없다
                    pass
                elif mode not in MODES and not args.all_modes:
                    pass
                else:
                    rec = Recording(out_dir, args)
                    rec.meta["game_mode"] = mode
                    rec.start()
            if rec is not None:
                rec.observe(live, stats)
                if not rec.alive():
                    log("ffmpeg가 멈췄어요. 화면 녹화 권한(macOS: 시스템 설정 > 개인정보 보호 > 화면 기록)을 확인해 주세요")
                    rec.stop()
                    rec.finish()
                    rec = None
                    give_up = True
        elif now - last_seen > GONE_AFTER:
            give_up = False

        if rec is not None:
            gone = not in_game and now - last_seen > GONE_AFTER
            ended = rec.ended_at is not None and now - rec.ended_at > TAIL
            if gone or ended:
                rec.stop()
                rec.finish()
                log(f"녹화 끝: {rec.dir} ({rec.meta.get('duration')}초)")
                take_lock(server.deliver(rec.dir))
                rec = None
                give_up = True  # 승패 화면에서도 API가 잠깐 살아 있으니, API가 사라질 때까지 새로 녹화하지 않는다

        locked = time.time() < lock_until
        if locked and not in_game:
            ph = lcu.stop_queue()
            lcu_state = "ok" if lcu.base else "missing"
            if ph:
                left = int(lock_until - time.time())
                log(f"복기 시간이라 큐를 취소했어요 ({ph}, {left // 60}분 {left % 60}초 남음)")
                server.blocked(ph)
        elif not locked:
            lcu_state = None

        if now - last_status > 5:
            last_status = now
            take_lock(server.status({
                "state": "recording" if rec else "waiting", "version": VERSION, "platform": platform.system(),
                "game_time": stats.get("gameTime") if (rec and stats) else None,
                "champion": (rec.meta.get("me") or {}).get("champion") if rec else None,
                "elapsed": round(rec.elapsed()) if rec else None,
                "pending": len(pending(out_dir)),
                "lock": lcu_state,
            }))
            if rec is None:
                for d in pending(out_dir):
                    take_lock(server.deliver(d))
                cleanup(out_dir, args.keep, args.local)
        time.sleep(1.0 if locked else POLL)  # 잠금 중엔 큐가 잡히기 전에 취소하려고 더 자주 본다

    if rec is not None:
        rec.stop()
        rec.finish()
        server.deliver(rec.dir)
    server.status({"state": "off", "version": VERSION, "platform": platform.system()})
    log("녹화 에이전트 종료")


if __name__ == "__main__":
    main()
