#!/usr/bin/env python3
"""미니맵을 1초마다 보고, 5초 간격 자료(minimap/ 시트)가 놓친 상대 챔피언 등장을 모은다.

    uv run tools/sightings.py <게임 폴더>

5초 간격으로는 상대 정글이 미니맵에 1~4초 보였다 사라진 순간을 놓친다. 정글러에게 가장 중요한 정보라
1초마다 미니맵에서 빨간 테두리 아이콘(상대 챔피언)을 찾고, 앞뒤 5초 프레임에 없던 위치에 2초 이상 보인 순간을
그 순간의 미니맵 원본 그대로 시트로 모은다(새로 보인 상대에 노란 원).
  minimap/sightings_001.jpg ...  4x4칸, 칸마다 VOD 시각
  game.json의 sighting_sheets    시트마다 담긴 VOD 시각 목록
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import hms, parse_time  # noqa: E402

SIZE = 346  # 1080p 미니맵을 자른 크기. 해상도가 달라도 이 크기로 맞춰서 아이콘 크기가 같다
TILE = 4    # 시트 한 장 = 4x4칸


def _ring(r: int, w: float = 2) -> np.ndarray:
    k = np.zeros((2 * r + 5, 2 * r + 5), np.float32)
    c = r + 2
    yy, xx = np.ogrid[:k.shape[0], :k.shape[1]]
    d = np.sqrt((xx - c) ** 2 + (yy - c) ** 2)
    k[(d >= r - w / 2) & (d <= r + w / 2)] = 1
    return k / k.sum()


RINGS = [_ring(r) for r in (11, 12, 13)]


def enemies(img: np.ndarray) -> list[tuple[int, int]]:
    """미니맵(BGR, SIZE x SIZE)에서 상대 챔피언 아이콘(빨간 원형 테두리) 중심들"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (((h < 10) | (h > 168)) & (s > 110) & (v > 110))
    score = np.max([cv2.filter2D(red.astype(np.float32), -1, k) for k in RINGS], axis=0)
    peak = (score >= cv2.dilate(score, np.ones((15, 15), np.uint8))) & (score > 0.45)
    out = []
    for y, x in zip(*np.where(peak)):
        y0, y1, x0, x1 = max(y - 18, 0), y + 19, max(x - 18, 0), x + 19
        sub = red[y0:y1, x0:x1]
        yy, xx = np.ogrid[y0 - y:y1 - y, x0 - x:x1 - x]
        d = np.sqrt(xx ** 2 + yy ** 2)
        # 속이 빨간 면(포탑, 핑)이나 큰 빨간 덩어리는 아이콘이 아니다
        if sub[d < 8].mean() < 0.25 and sub[(d > 15) & (d < 18)].mean() < 0.35:
            out.append((int(x), int(y)))
    return out


def _near(p, ps, r: int = 25) -> bool:
    return any((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 < r * r for q in ps)


def scan(video: Path, start_off: float, crop: str, step: int = 5) -> list[dict]:
    """영상 start_off초부터 1초마다 미니맵을 보고, 5초 간격 프레임이 놓친 상대 등장을 돌려준다.

    반환: [{"sec": 영상 안 초, "fresh": [(x, y)], "img": 미니맵}]"""
    x, y, w, h = (float(v) for v in crop.split(","))
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start_off:.3f}", "-i", str(video), "-vf",
           f"fps=1,crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale={SIZE}:{SIZE}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    frames, pos = [], []
    n = SIZE * SIZE * 3
    assert p.stdout
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        img = np.frombuffer(b, np.uint8).reshape(SIZE, SIZE, 3)
        pos.append(enemies(img))
        frames.append(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1])  # 메모리 아끼려고 압축해 둔다
    p.wait()

    hits = []
    for i in range(len(pos)):
        if i % step == 0:
            continue
        a, b = (i // step) * step, min((i // step) * step + step, len(pos) - 1)
        # 앞뒤 5초 프레임보다 상대가 더 많이 보이고, 그 프레임들에 없던 자리에 있다
        if len(pos[i]) <= max(len(pos[a]), len(pos[b])):
            continue
        fresh = [q for q in pos[i] if not _near(q, pos[a]) and not _near(q, pos[b])]
        if fresh:
            hits.append((i, fresh))
    groups: list[list] = []
    for i, fresh in hits:
        if groups and i - groups[-1][-1][0] <= 2:
            groups[-1].append((i, fresh))
        else:
            groups.append([(i, fresh)])
    out = []
    for g in groups:
        if len(g) < 2:  # 1초만 잡힌 건 오검출일 수 있다
            continue
        i, fresh = max(g, key=lambda e: len(e[1]))
        out.append({"sec": i, "fresh": fresh, "img": cv2.imdecode(frames[i], cv2.IMREAD_COLOR), "span": len(g)})
    return out


def build(gdir: Path, video: Path, start: float, start_off: float, crop: str, step: int = 5) -> list[dict]:
    """시트를 만들고 game.json에 넣을 목록을 돌려준다. start = 게임 시작 VOD 시각, start_off = 영상 안에서 게임 시작 위치(초)"""
    hits = scan(video, start_off, crop, step)
    (gdir / "minimap").mkdir(exist_ok=True)
    for old in (gdir / "minimap").glob("sightings_*.jpg"):
        old.unlink()
    sheets = []
    per = TILE * TILE
    for k in range(0, len(hits), per):
        chunk = hits[k:k + per]
        tiles = []
        for hit in chunk:
            img = hit["img"].copy()
            for (x, y) in hit["fresh"]:
                cv2.circle(img, (x, y), 16, (0, 255, 255), 2)
            cv2.rectangle(img, (0, 0), (118, 26), (0, 0, 0), -1)
            cv2.putText(img, hms(start + hit["sec"]), (5, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
            tiles.append(img)
        while len(tiles) % TILE:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[r:r + TILE]) for r in range(0, len(tiles), TILE)]
        name = f"sightings_{k // per + 1:03d}.jpg"
        cv2.imwrite(str(gdir / "minimap" / name), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
        sheets.append({"file": f"minimap/{name}", "times": [hms(start + h["sec"]) for h in chunk]})
    print(f"5초 간격이 놓친 상대 등장 {len(hits)}번 → 시트 {len(sheets)}장 (minimap/sightings_*.jpg)", flush=True)
    return sheets


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir")
    gdir = Path(ap.parse_args().game_dir).resolve()
    meta = json.loads((gdir / "game.json").read_text())
    start = parse_time(meta["start"])
    vstart = parse_time(meta.get("video_start") or meta["start"])
    meta["sighting_sheets"] = build(gdir, gdir / "video.mp4", start, start - vstart,
                                    meta.get("minimap_crop") or "0.82,0.68,0.18,0.32", int(meta.get("minimap_interval") or 5))
    (gdir / "game.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
