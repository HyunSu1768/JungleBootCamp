"""스캔/추출 스크립트가 같이 쓰는 도우미."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.platform_util import MAC, WINDOWS, hide_console_windows  # noqa: E402

hide_console_windows()  # Windows: ffmpeg, yt-dlp가 콘솔 창을 띄우지 않게
VODS = Path(os.environ.get("JUNGLE_VODS", ROOT / "vods")).resolve()
# drawtext 글꼴. Windows 경로의 콜론은 ffmpeg 필터 문법 때문에 작은따옴표 안에서 이스케이프한다(두 단계 파싱)
FONT = ("'C\\:/Windows/Fonts/arial.ttf'" if WINDOWS else
        "/System/Library/Fonts/Supplemental/Arial.ttf" if MAC else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
# macOS(Apple 실리콘)는 mlx-whisper, 그 밖에는 faster-whisper. 둘 다 large-v3 계열이 팀 보이스, 롤 용어를 잘 알아듣는다
WHISPER_MODEL = os.environ.get("JUNGLE_WHISPER_MODEL") or (
    "mlx-community/whisper-large-v3-mlx" if MAC else "large-v3-turbo")  # CPU에선 turbo가 large-v3보다 몇 배 빠르다
YTDLP = [sys.executable, "-m", "yt_dlp"]  # 따로 설치한 yt-dlp.exe 없이 파이썬 패키지로
# 받아쓰기 정확도를 높이려고 Whisper에 주는 용어 힌트
LOL_PROMPT = (
    "리그 오브 레전드 정글 방송. 갱킹, 카정, 풀캠, 동선, 바위게, 스커틀, 용, 드래곤, "
    "유충, 공허 유충, 전령, 바론, 아타칸, 탑, 미드, 바텀, 원딜, 서폿, 점멸, 강타, "
    "와드, 제어 와드, 시야, 귀환, 백, 웨이브, 라인 주도권, 다이브, 한타, 스플릿."
)


def die(msg: str) -> None:
    print(f"오류: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], quiet: bool = False) -> str:
    """명령을 실행하고 stdout을 돌려준다. 실패하면 stderr를 보여주고 종료."""
    if not quiet:
        print("$ " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        die(f"{cmd[0]} 실패 (code {p.returncode})\n{p.stderr[-3000:]}")
    return p.stdout


def run_live(cmd: list[str]) -> None:
    """진행 상황이 보이도록 출력을 그대로 흘려보내며 실행."""
    print("$ " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""), flush=True)
    p = subprocess.run(cmd)
    if p.returncode != 0:
        die(f"{cmd[0]} 실패 (code {p.returncode})")


def hms(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_time(s: str) -> float:
    """'1:23:45', '83:45', '5025' 모두 초로 바꾼다."""
    parts = [float(p) for p in s.strip().split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def probe_duration(path: Path) -> float:
    out = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        quiet=True,
    )
    return float(out.strip())


def safe_name(s: str, limit: int = 40) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", s).strip("_")
    return s[:limit] or "vod"


def is_local(url: str) -> bool:
    """내 게임 녹화처럼 이미 디스크에 있는 영상 파일인가"""
    return "://" not in url and Path(url).is_file()


def vod_info(url: str) -> dict:
    """yt-dlp 메타데이터. 여러 파트로 나뉜 VOD면 entries가 들어 있다. 로컬 파일이면 ffprobe로 길이만."""
    if is_local(url):
        p = Path(url)
        return {"id": p.parent.name, "title": p.name, "uploader": "", "duration": probe_duration(p), "local": True}
    return json.loads(run([*YTDLP, "-J", "--no-warnings", url]))


def require_tools() -> None:
    import importlib.util
    if not importlib.util.find_spec("yt_dlp"):
        die("yt-dlp 파이썬 패키지가 없습니다 (uv sync)")
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            die(f"{t}가 설치돼 있지 않습니다")


def drawtext_clock(offset: float, size: int) -> str:
    """프레임 왼쪽 위에 VOD 기준 시각(H:MM:SS)을 찍는 drawtext 필터."""
    return (
        f"drawtext=fontfile={FONT}:fontsize={size}:fontcolor=yellow:box=1:boxcolor=black@0.7:"
        f"x=4:y=4:text='%{{pts\\:hms\\:{offset:.3f}}}'"
    )


def _whisper_segments(audio: Path) -> list[dict]:
    if MAC:
        import mlx_whisper  # 무거워서 필요할 때만 불러온다
        result = mlx_whisper.transcribe(
            str(audio), path_or_hf_repo=WHISPER_MODEL, language="ko", initial_prompt=LOL_PROMPT,
            condition_on_previous_text=False,  # 같은 문장 반복 환각 방지
            verbose=None,
        )
        return result["segments"]
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
    except Exception:  # noqa: BLE001  CUDA가 없으면 CPU
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(audio), language="ko", initial_prompt=LOL_PROMPT,
                               condition_on_previous_text=False, vad_filter=True)
    out = []
    for s in segs:
        out.append({"start": s.start, "end": s.end, "text": s.text})
        if len(out) % 50 == 0:
            print(f"  받아쓰기 {hms(s.end)}까지", flush=True)
    return out


def transcribe(audio: Path, offset: float, out_md: Path, out_json: Path) -> None:
    """한국어 받아쓰기. 타임스탬프는 VOD 기준(offset 더함)."""
    print(f"받아쓰기 중: {audio.name} (모델 {WHISPER_MODEL})", flush=True)
    segs = []
    last_text = None
    for s in _whisper_segments(audio):
        text = s["text"].strip()
        if not text or text == last_text:
            continue
        last_text = text
        segs.append({"start": s["start"] + offset, "end": s["end"] + offset, "text": text})
    out_json.write_text(json.dumps(segs, ensure_ascii=False, indent=1))
    lines = [f"[{hms(s['start'])}] {s['text']}" for s in segs]
    out_md.write_text("\n".join(lines) + "\n")
    print(f"받아쓰기 완료: {len(segs)}문장 → {out_md}", flush=True)
