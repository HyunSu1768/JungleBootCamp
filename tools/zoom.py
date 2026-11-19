#!/usr/bin/env python3
"""3단계: 교전 같은 짧은 순간을 촘촘하게(기본 초당 4장) 뽑는다.

extract.py로 받아 둔 video.mp4에서 자르므로 다시 다운로드하지 않는다.

    uv run tools/zoom.py vods/<id>_<스트리머>/game2 --at 1:26:40 [--before 8 --after 12 --fps 4]

만들어지는 것 (게임 폴더/zoom/<시각>/):
  frames/       원본 해상도 프레임 (파일명 = VOD 시각, 밀리초 포함)
  sheet_*.jpg   12장씩 묶은 시트 (1장 = 3초 @4fps) → 흐름을 먼저 보고 필요한 프레임만 원본으로
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, die, drawtext_clock, hms, parse_time, run  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir", help="extract.py가 만든 게임 폴더")
    ap.add_argument("--at", required=True, help="중심 시각 (VOD 시각), 예: 1:26:40")
    ap.add_argument("--before", type=float, default=8)
    ap.add_argument("--after", type=float, default=12)
    ap.add_argument("--fps", type=float, default=4)
    args = ap.parse_args()

    gdir = Path(args.game_dir)
    if not gdir.is_absolute():
        gdir = ROOT / gdir
    meta_path = gdir / "game.json"
    if not meta_path.exists():
        die(f"{meta_path}가 없습니다. extract.py를 먼저 실행하세요.")
    meta = json.loads(meta_path.read_text())
    game_start = parse_time(meta.get("video_start") or meta["start"])  # 영상 첫 프레임의 VOD 시각
    at = parse_time(args.at)
    t0 = max(game_start, at - args.before)
    length = at + args.after - t0
    if length <= 0:
        die("구간이 게임 범위를 벗어났습니다")

    zdir = gdir / "zoom" / hms(at).replace(":", "-")
    fdir = zdir / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    for old in list(fdir.glob("*.jpg")) + list(zdir.glob("sheet_*.jpg")):
        old.unlink()

    common_in = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", f"{t0 - game_start:.3f}", "-t", f"{length:.3f}", "-i", str(gdir / "video.mp4")]
    run(common_in + ["-vf", f"fps={args.fps},{drawtext_clock(t0, 30)}",
                     "-q:v", "2", str(fdir / "%05d.jpg")], quiet=True)
    step = 1 / args.fps
    frames = sorted(fdir.glob("*.jpg"))
    for i, f in enumerate(frames):
        t = t0 + i * step
        f.rename(f.with_name(f"{hms(t).replace(':', '-')}.{int(round((t % 1) * 1000)):03d}.jpg"))

    run(common_in + ["-vf", f"fps={args.fps},scale=640:-2,{drawtext_clock(t0, 20)},tile=4x3",
                     "-q:v", "3", str(zdir / "sheet_%03d.jpg")], quiet=True)

    sheets = sorted(zdir.glob("sheet_*.jpg"))
    print(f"완료 → {zdir}")
    print(f"  {hms(t0)} ~ {hms(t0 + length)}, 프레임 {len(frames)}장, 시트 {len(sheets)}장 (시트 1장 = {12 * step:.1f}초)")


if __name__ == "__main__":
    main()
