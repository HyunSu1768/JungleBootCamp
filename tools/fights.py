#!/usr/bin/env python3
"""교전 후보 찾기: 음량이 평소보다 확 커진 구간 + 받아쓰기의 교전 관련 말.

extract.py가 자동으로 부른다. 따로 돌릴 때:

    uv run tools/fights.py vods/<id>_<스트리머>/game2

결과: 게임 폴더/fight_candidates.md (후보마다 VOD 시각, 음량 점수, 근처 발언)
어디까지나 '후보'다. 실제 교전인지는 프레임을 보고 판단한다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, die, hms, parse_time  # noqa: E402

FIGHT_WORDS = re.compile(
    r"한타|싸움|싸워|싸우|죽었|죽어|죽여|죽이|킬|잡았|잡아|잡혔|다이브|점멸|궁|들어가|들어와|빠져|도망|"
    r"살았|살려|더블|트리플|쿼드라|펜타|교전|맞다이|갱|물렸|물어|이니시|따였|땄"
)
RATE = 8000
BASELINE_SEC = 60   # 이 길이의 중앙값을 '평소 음량'으로 본다
THRESHOLD_DB = 6    # 평소보다 이만큼 크면 후보
MERGE_SEC = 10      # 이 안에 붙어 있는 후보는 하나로
TOP_N = 15


def loudness_events(audio: Path) -> list[dict]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(audio),
                        "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"], capture_output=True)
    if p.returncode != 0:
        die(f"오디오 디코딩 실패: {p.stderr.decode()[-500:]}")
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // RATE
    if n < 30:
        return []
    rms = np.sqrt(np.mean(x[: n * RATE].reshape(n, RATE) ** 2, axis=1) + 1e-10)
    db = 20 * np.log10(rms)
    half = BASELINE_SEC // 2
    base = np.array([np.median(db[max(0, i - half): i + half + 1]) for i in range(n)])
    score = db - base

    events: list[dict] = []
    for i in np.where(score > THRESHOLD_DB)[0]:
        if events and i - events[-1]["end"] <= MERGE_SEC:
            ev = events[-1]
            ev["end"] = int(i)
            if score[i] > ev["score"]:
                ev["score"], ev["peak"] = float(score[i]), int(i)
        else:
            events.append({"start": int(i), "end": int(i), "peak": int(i), "score": float(score[i])})
    return events


def has_audio(path: Path) -> bool:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return bool(p.stdout.strip())


def live_fights(gdir: Path) -> list[str]:
    """내 게임: 롤 클라이언트가 남긴 킬 기록(live.json)으로 교전을 정확히 묶는다"""
    lj = gdir.parent / "live.json"
    if not lj.exists():
        return []
    live = json.loads(lj.read_text())
    off = live.get("offset") or 0
    kills = [e for e in live.get("events", []) if e.get("EventName") == "ChampionKill"]
    groups: list[list[dict]] = []
    for e in kills:
        if groups and e["EventTime"] - groups[-1][-1]["EventTime"] <= 15:
            groups[-1].append(e)
        else:
            groups.append([e])
    me = ((live.get("me") or {}).get("riot_id") or "").split("#")[0]
    out = ["## 게임 기록으로 확인한 교전 (정확한 시각)", "",
           "롤 클라이언트가 남긴 킬 기록이에요. 시각은 녹화 시각(인게임 시각)이에요.", ""]
    for k, g in enumerate(groups, 1):
        t0 = g[0]["EventTime"]
        out.append(f"### 교전 {k}. 녹화 {hms(t0 + off)} (인게임 {int(t0 // 60)}:{int(t0 % 60):02d}), 킬 {len(g)}개")
        for e in g:
            who = lambda n: f"**{n}(나)**" if me and n.split("#")[0] == me else n  # noqa: E731
            assists = ", ".join(who(a) for a in e.get("Assisters") or [])
            out.append(f"- {int(e['EventTime'] // 60)}:{int(e['EventTime'] % 60):02d} {who(e.get('KillerName', '?'))} → {who(e.get('VictimName', '?'))}"
                       + (f" (도움: {assists})" if assists else ""))
        out.append("")
    return out


def find(gdir: Path) -> Path:
    meta = json.loads((gdir / "game.json").read_text())
    start = parse_time(meta.get("video_start") or meta["start"])  # 영상 첫 프레임의 VOD 시각
    game_off = parse_time(meta["start"]) - start  # 픽창 구간은 교전 후보에서 뺀다
    audio = gdir / "audio.m4a"
    if not audio.exists():
        audio = gdir / "video.mp4"
    events = [e for e in loudness_events(audio) if e["peak"] >= game_off] if has_audio(audio) else []
    events = sorted(events, key=lambda e: -e["score"])[:TOP_N]
    events.sort(key=lambda e: e["peak"])

    tpath = gdir / "transcript.json"
    lines = json.loads(tpath.read_text()) if tpath.exists() else []
    fight_lines = [s for s in lines if FIGHT_WORDS.search(s["text"]) and s["start"] >= start + game_off]

    out = ["# 교전 후보", "",
           "음량이 평소보다 확 커진 구간(스트리머 반응, 스킬 소리)과 근처 발언입니다. "
           "실제 교전인지는 프레임을 보고 판단하세요.",
           f"확대: `uv run tools/zoom.py {gdir.relative_to(ROOT) if gdir.is_relative_to(ROOT) else gdir} --at <시각>`", ""]
    covered: set[int] = set()
    for k, e in enumerate(events, 1):
        peak = start + e["peak"]
        near = [s for s in lines if peak - 12 <= s["start"] <= peak + 8]
        covered.update(id(s) for s in near)
        out.append(f"## {k}. VOD {hms(peak)}  (음량 +{e['score']:.0f}dB, "
                   f"{hms(start + e['start'])}~{hms(start + e['end'])})")
        out += [f"- [{hms(s['start'])}] {s['text']}" for s in near] or ["- (발언 없음)"]
        out.append("")

    extra = [s for s in fight_lines if id(s) not in covered]
    if extra:
        out += ["## 음량 변화는 없지만 교전 관련 발언이 나온 곳", ""]
        out += [f"- [{hms(s['start'])}] {s['text']}" for s in extra]
        out.append("")

    out += live_fights(gdir)
    path = gdir / "fight_candidates.md"
    path.write_text("\n".join(out))
    print(f"교전 후보 {len(events)}개 (+발언만 {len(extra)}개) → {path}")
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        die("사용법: uv run tools/fights.py <게임 폴더>")
    g = Path(sys.argv[1])
    find(g if g.is_absolute() else ROOT / g)
