#!/usr/bin/env python3
"""공유받은 프로 판의 영상만 받는다 (장면 다시 보기, 예측 훈련용).

    uv run tools/fetch_video.py <vod 폴더 이름> <판 번호> [--height 720]

릴리스에 같이 들어온 분석에는 영상이 없다(판 하나에 수 GB). game.json에 적힌 숲 VOD 구간
(video_start ~ end)과 리플레이 피드백 구간만 받아서 분석 때와 같은 이름(video.mp4, review/seg<n>.mp4)으로 둔다.
분석 때와 같은 구간이라 분석의 시각이 그대로 맞는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import VODS, die, hms, parse_time, probe_duration, vod_info  # noqa: E402
from extract import download, locate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vod")
    ap.add_argument("n", type=int)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    vdir = VODS / args.vod
    gdir = vdir / f"game{args.n}"
    meta = json.loads((gdir / "game.json").read_text())
    url = meta.get("url")
    if not url or not url.startswith("http"):
        die("이 판은 숲 VOD 주소가 없어서 영상을 받을 수 없어요")
    # 나중에 이 판을 다시 분석해도 영상을 다시 받지 않게, 분석(extract.py)과 같은 구간 기준(games.json)을 쓴다
    g = next((x for x in json.loads((vdir / "games.json").read_text()).get("games", []) if x.get("n") == args.n), {}) \
        if (vdir / "games.json").exists() else {}
    vstart = parse_time(g.get("draft_start") or g.get("start") or meta.get("video_start") or meta["start"])
    end = parse_time(g.get("end") or meta["end"])
    info = vod_info(url)

    video = gdir / "video.mp4"
    if not video.exists():
        print(f"영상 받기: {hms(vstart)} ~ {hms(end)} ({(end - vstart) / 60:.0f}분, {args.height}p)", flush=True)
        download(url, locate(vdir, info, vstart, end), video, args.height)
        if not video.exists():
            die("영상을 받지 못했어요")
        (gdir / "video.json").write_text(json.dumps({"vstart": round(vstart), "end": round(end)}))
        print(f"받았어요: {hms(probe_duration(video))}", flush=True)

    for i, r in enumerate(meta.get("reviews") or [], 1):
        seg = gdir / "review" / f"seg{i}.mp4"
        if seg.exists() or not r.get("from") or not r.get("to"):
            continue
        seg.parent.mkdir(parents=True, exist_ok=True)
        a, b = parse_time(r["from"]), parse_time(r["to"])
        print(f"리플레이 피드백 {i}: {hms(a)} ~ {hms(b)}", flush=True)
        download(url, locate(vdir, info, a, b), seg, 720)
    reviews = [r for r in meta.get("reviews") or [] if r.get("from") and r.get("to")]
    if reviews and all((gdir / "review" / f"seg{i}.mp4").exists() for i in range(1, len(reviews) + 1)):
        (gdir / "review" / "review.json").write_text(json.dumps([[round(parse_time(r["from"])), round(parse_time(r["to"]))] for r in reviews]))
    print("영상 준비 끝", flush=True)


if __name__ == "__main__":
    main()
