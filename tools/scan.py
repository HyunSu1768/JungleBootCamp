#!/usr/bin/env python3
"""1단계: 긴 VOD를 최저화질로 받아 1분 간격 썸네일 시트를 만든다.

시트를 보고 게임이 몇 판인지, 각 판이 VOD의 몇 시 몇 분에 있는지 찾는다.

    uv run tools/scan.py <숲 다시보기 링크> [--interval 60] [--transcribe]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    VODS, YTDLP, die, drawtext_clock, hms, probe_duration, require_tools, run, run_live,
    safe_name, transcribe, vod_info,
)

COLS, ROWS = 8, 6  # 시트 1장 = 48칸


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--interval", type=int, default=60, help="썸네일 간격(초), 기본 60")
    ap.add_argument("--transcribe", action="store_true", help="VOD 전체 음성도 받아쓰기 (8시간이면 수십 분 걸림)")
    args = ap.parse_args()
    require_tools()

    info = vod_info(args.url)
    entries = info.get("entries") or [info]
    title = info.get("title") or entries[0].get("title") or "vod"
    uploader = info.get("uploader") or entries[0].get("uploader") or ""
    vod_id = str(info.get("id") or entries[0].get("id"))
    vdir = VODS / f"{vod_id}_{safe_name(uploader, 20)}"
    sdir = vdir / "scan"
    sheets_dir = sdir / "sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    (vdir / "info.json").write_text(json.dumps(
        {"url": args.url, "id": vod_id, "title": title, "uploader": uploader,
         "parts": len(entries)}, ensure_ascii=False, indent=1))
    print(f"VOD: {title} / {uploader} / 파트 {len(entries)}개 → {vdir}")
    print(f"VOD_DIR={vdir.name}", flush=True)  # 웹 서버가 이 줄로 폴더를 알아낸다

    # 최저화질 다운로드 (이미 받았으면 건너뜀)
    if not sorted(sdir.glob("part_*.mp4")):
        run_live([
            *YTDLP, "--no-warnings", "-N", "8",
            "-f", "w[height>=240]/w/wv*+wa",
            "--merge-output-format", "mp4",
            # 파트가 여러 개인 VOD를 yt-dlp가 기본값(multi_video)으로 하나로 이어 붙이면
            # 파트 경계를 잃어 extract.py가 엉뚱한 구간을 받는다. 파트별 파일로 둔다.
            "--concat-playlist", "never",
            "-o", str(sdir / "part_%(playlist_index|1)s.%(ext)s"),
            args.url,
        ])
    files = sorted(sdir.glob("part_*.mp4"), key=lambda p: int(p.stem.split("_")[1]))
    if not files:
        die("다운로드된 파일이 없습니다. 링크가 맞는지, 로그인/구독 전용 VOD인지 확인하세요.")

    # 파트가 여러 개면 이어 붙인 '전체 VOD 시각'으로 통일한다
    parts, offset = [], 0.0
    for i, f in enumerate(files, 1):
        dur = probe_duration(f)
        parts.append({"part": i, "file": f.name, "start": offset, "duration": dur})
        offset += dur

    sheets = []
    per_sheet = COLS * ROWS * args.interval
    for p in parts:
        prefix = f"p{p['part']}_" if len(parts) > 1 else ""
        pattern = sheets_dir / f"{prefix}sheet_%03d.jpg"
        vf = ",".join([
            f"fps=1/{args.interval}",
            "scale=320:-2",
            drawtext_clock(p["start"], 22),
            f"tile={COLS}x{ROWS}",
        ])
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-skip_frame", "nokey", "-i", str(sdir / p["file"]),
             "-vf", vf, "-q:v", "4", str(pattern)])
        for n, img in enumerate(sorted(sheets_dir.glob(f"{prefix}sheet_*.jpg"))):
            start = p["start"] + n * per_sheet
            end = min(start + per_sheet, p["start"] + p["duration"])
            sheets.append({"file": f"sheets/{img.name}", "from": hms(start), "to": hms(end)})

    scan = {"interval": args.interval, "total": hms(offset), "parts": parts, "sheets": sheets}
    (sdir / "scan.json").write_text(json.dumps(scan, ensure_ascii=False, indent=1))

    if args.transcribe:
        for p in parts:
            audio = sdir / f"audio_{p['part']}.m4a"
            if not audio.exists():
                run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                     str(sdir / p["file"]), "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k", str(audio)])
            transcribe(audio, p["start"], sdir / f"transcript_{p['part']}.md",
                       sdir / f"transcript_{p['part']}.json")

    print(f"\n전체 길이 {hms(offset)}, 시트 {len(sheets)}장")
    for s in sheets:
        print(f"  {sdir / s['file']}  ({s['from']} ~ {s['to']})")


if __name__ == "__main__":
    main()
