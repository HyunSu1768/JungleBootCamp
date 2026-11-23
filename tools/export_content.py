#!/usr/bin/env python3
"""분석한 프로 판을 앱에 같이 넣을 공유 콘텐츠(content/)로 내보낸다.

    uv run tools/export_content.py                 # vods/의 분석한 프로 판 전부
    uv run tools/export_content.py --vods <폴더>   # 다른 곳(예: Windows 앱 데이터 폴더의 vods)에서

content/는 저장소에 커밋되고, 릴리스 설치 파일에 들어간다. 앱은 켤 때 이걸 사용자 데이터에 합친다(server/content.py).
영상(video.mp4)과 받아쓰기는 넣지 않는다. 분석(analysis.json), 판 정보(game.json), 분석이 가리키는 이미지,
VOD 정보(info.json, games.json, 썸네일)만 넣는다. 영상은 사용자가 원할 때 앱이 숲에서 그 판 구간만 받는다.
kb/(개념, 원칙, 복습 문제)는 원래 저장소에 있고, 복습 문제가 쓰는 이미지만 여기에 같이 넣는다.

내 게임(vods/mine/)은 개인 녹화라 절대 내보내지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = re.compile(r'"([^"\s]+\.(?:jpg|jpeg|png|webp))"')
GAME_FILES = ("analysis.json", "game.json")
VOD_FILES = ("info.json", "games.json")
PRIVATE = re.compile(r"/Users/|\\\\Users\\\\|C:\\\\Users|/home/")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def images(text: str, vods: Path) -> set[str]:
    """JSON 안의 이미지 경로(VODS 기준 상대 경로) 중 실제로 있는 것"""
    out = set()
    for ref in IMG.findall(text):
        if ref.startswith(("/", "http")) or ".." in ref:
            continue
        if (vods / ref).is_file():
            out.add(ref)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vods", default=str(ROOT / "vods"))
    ap.add_argument("--kb", default=str(ROOT / "kb"))
    ap.add_argument("--out", default=str(ROOT / "content"))
    args = ap.parse_args()
    vods, out = Path(args.vods).resolve(), Path(args.out).resolve()

    games = []
    for a in sorted(vods.glob("*/game*/analysis.json")):
        vod = a.parent.parent.name
        if vod.startswith("_") or vod == "mine":
            continue
        try:
            data = json.loads(a.read_text())
        except json.JSONDecodeError:
            print(f"건너뜀(깨진 JSON): {a}")
            continue
        if data.get("own") or (data.get("version") or 1) < 2:
            continue
        games.append((vod, a.parent))
    if not games:
        sys.exit("내보낼 분석이 없어요")

    staging = out.with_name(out.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "vods").mkdir(parents=True)
    manifest = {"exported": time.strftime("%Y-%m-%dT%H:%M:%S"), "games": [], "vods": {}, "files": {}}

    def put(rel: str) -> None:
        src = vods / rel
        dst = staging / "vods" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".json" and PRIVATE.search(src.read_text()):
            sys.exit(f"개인 경로가 들어 있어서 멈췄어요: {src}")
        shutil.copy2(src, dst)
        manifest["files"][rel] = sha(dst)

    for vod, gdir in games:
        rel = f"{vod}/{gdir.name}"
        files = [f"{rel}/{f}" for f in GAME_FILES if (gdir / f).exists()]
        text = "".join((gdir / f).read_text() for f in GAME_FILES if (gdir / f).exists())
        imgs = sorted(images(text, vods))
        for f in files + imgs:
            put(f)
        a = json.loads((gdir / "analysis.json").read_text())
        manifest["games"].append({"vod": vod, "game": gdir.name, "champion": a.get("champion"),
                                  "enemy_jungler": a.get("enemy_jungler"), "streamer": a.get("streamer"),
                                  "files": files + imgs})
        if vod not in manifest["vods"]:
            vfiles = [f"{vod}/{f}" for f in VOD_FILES if (vods / vod / f).exists()]
            vfiles += [f"{vod}/thumbs/{t.name}" for t in sorted((vods / vod / "thumbs").glob("*.jpg"))]
            for f in vfiles:
                put(f)
            manifest["vods"][vod] = vfiles

    # 복습 문제(kb/quizzes.json)가 쓰는 장면 이미지
    kb_imgs = sorted(images((Path(args.kb) / "quizzes.json").read_text(), vods)) if (Path(args.kb) / "quizzes.json").exists() else []
    for f in kb_imgs:
        if f not in manifest["files"]:
            put(f)
    manifest["kb_images"] = kb_imgs

    (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    shutil.rmtree(out, ignore_errors=True)
    staging.replace(out)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"판 {len(games)}개, 파일 {len(manifest['files'])}개, {size / 1e6:.1f}MB → {out}")
    for g in manifest["games"]:
        print(f"  {g['vod']}/{g['game']}: {g['streamer']} {g['champion']} vs {g['enemy_jungler']}")


if __name__ == "__main__":
    main()
