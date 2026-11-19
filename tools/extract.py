#!/usr/bin/env python3
"""2단계: 고른 게임 한 판만 고화질로 받아 분석 재료를 만든다.

    uv run tools/extract.py <링크> --draft-start 1:20:30 --start 1:23:00 --end 1:58:30 --name game2

시각은 scan 시트에 찍힌 '전체 VOD 시각' 그대로 쓰면 된다.
  --draft-start  픽창이 처음 보이는 시각 (생략하면 밴픽 자료 없이 게임만)
  --start        게임 화면(인게임 HUD)이 처음 보이는 시각
만들어지는 것 (vods/<id>/<name>/):
  draft/          픽창 2초 간격 원본 해상도 + 시트 → 밴픽 분석용
  frames/         5초 간격 전체 화면 (파일명 = VOD 시각)
  minimap/        5초 간격 미니맵 시트 (1장 = 2분 30초) → 턴, 동선 추적용
  overview/       30초 간격 전체 화면 시트 (1장 = 8분) → 흐름 파악용
  minimap_check.jpg  미니맵 자르기 영역 확인용 (빨간 상자)
  transcript.md   스트리머 음성 받아쓰기 (VOD 시각)
  fight_candidates.md  교전 후보 (음량 급등 + 교전 관련 발언) → tools/zoom.py로 확대
  review/         games.json에 이 판의 리플레이 피드백 구간(reviews)이 있으면: 받아쓰기, 5초 프레임, 20초 시트
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    VODS, YTDLP, die, drawtext_clock, hms, is_local, parse_time, probe_duration, require_tools, run,
    run_live, safe_name, transcribe, vod_info,
)


def find_vod_dir(url: str) -> tuple[Path, dict]:
    info = vod_info(url)
    if info.get("local"):
        return Path(url).resolve().parent, info  # 내 게임: 녹화 파일이 있는 폴더
    entries = info.get("entries") or [info]
    vod_id = str(info.get("id") or entries[0].get("id"))
    matches = sorted(VODS.glob(f"{vod_id}_*"))
    if matches:
        return matches[0], info
    uploader = info.get("uploader") or entries[0].get("uploader") or ""
    return VODS / f"{vod_id}_{safe_name(uploader, 20)}", info


def locate(vdir: Path, info: dict, start: float, end: float) -> list[tuple[int | None, float, float]]:
    """전체 VOD 시각을 [(파트 번호, 파트 안 시작, 파트 안 끝), ...]으로 바꾼다.

    게임이 파트 경계에 걸치면 조각이 둘 이상 나온다.
    """
    # 파트 나눔은 yt-dlp가 내려받는 단위(entries)를 따른다.
    # scan은 파트를 이어 붙여 한 파일로 받았을 수 있어서 scan.json의 parts와 다를 수 있다.
    entries = info.get("entries") or []
    if len(entries) > 1 and all(e.get("duration") for e in entries):
        parts, off = [], 0.0
        for i, e in enumerate(entries, 1):
            parts.append({"part": i, "start": off, "duration": float(e["duration"])})
            off += float(e["duration"])
    elif (vdir / "scan" / "scan.json").exists():
        parts = json.loads((vdir / "scan" / "scan.json").read_text())["parts"]
    else:
        parts = [{"part": 1, "start": 0.0, "duration": float(info.get("duration") or 1e9)}]
    if len(parts) == 1:
        return [(None, start, end)]
    segs = []
    for p in parts:
        ps, pe = p["start"], p["start"] + p["duration"]
        if start < pe and end > ps:
            segs.append((p["part"], max(start, ps) - ps, min(end, pe) - ps))
    if not segs:
        die("시작 시각이 VOD 범위를 벗어났습니다")
    return segs


def ffmpeg(args: list[str]) -> None:
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])


def keyframe_gap(video: Path, seconds: int = 40) -> float:
    """앞부분 키프레임 사이 최대 간격(초). 짧으면 키프레임만 디코딩해 프레임을 뽑을 수 있다(4배쯤 빠름)."""
    out = run(["ffprobe", "-v", "error", "-select_streams", "v", "-skip_frame", "nokey", "-show_entries", "frame=pts_time",
               "-of", "csv=p=0", "-read_intervals", f"%+{seconds}", str(video)], quiet=True)
    ts = []
    for x in out.split():
        try:
            ts.append(float(x.strip(",")))
        except ValueError:
            pass
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    return max(gaps) if len(gaps) >= 3 else 99.0


class Background(threading.Thread):
    """ffmpeg 작업을 받아쓰기와 동시에 돌린다. 안에서 난 오류(die 포함)는 join_or_raise에서 다시 던진다."""

    def __init__(self, fn, *args):
        super().__init__(daemon=True)
        self.fn, self.args, self.error = fn, args, None
        self.result = None

    def run(self) -> None:
        try:
            self.result = self.fn(*self.args)
        except BaseException as e:  # noqa: BLE001  SystemExit(die)도 잡는다
            self.error = e

    def join_or_raise(self):
        self.join()
        if self.error:
            raise self.error
        return self.result


def faststart(video: Path) -> None:
    """mp4 색인(moov)을 파일 앞으로 옮긴다. 웹에서 영상을 바로 열고 원하는 시점으로 넘기려면 필요하다."""
    with video.open("rb") as f:
        if b"moov" in f.read(1 << 20):
            return
    tmp = video.with_name(video.stem + "_fs.mp4")
    ffmpeg(["-i", str(video), "-c", "copy", "-movflags", "+faststart", str(tmp)])
    tmp.replace(video)


def stream_info(src: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,height", "-of", "json", str(src)], quiet=True)
    streams = json.loads(out).get("streams", [])
    v = next((x for x in streams if x.get("codec_type") == "video"), {})
    return {"vcodec": v.get("codec_name"), "height": v.get("height") or 0, "audio": any(x.get("codec_type") == "audio" for x in streams)}


def cut_local(src: Path, start: float, end: float, out: Path, height: int) -> None:
    """내 게임 녹화에서 구간을 잘라 웹에서 바로 재생되는 mp4로. 코덱이 맞으면 다시 인코딩하지 않는다."""
    si = stream_info(src)
    span = ["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?"]
    if si["vcodec"] == "h264" and si["height"] <= height:
        try:
            ffmpeg([*span, "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
            return
        except SystemExit:
            out.unlink(missing_ok=True)
    print(f"녹화({si['vcodec']}, {si['height']}p)를 웹용 h264로 바꿉니다. 판 길이만큼 걸릴 수 있어요", flush=True)
    ffmpeg([*span, "-vf", f"scale=-2:'min({height},ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])


def download(url: str, segs: list[tuple[int | None, float, float]], out: Path, height: int) -> None:
    """VOD 구간을 받아 out(mp4) 하나로 만든다. 파트 경계에 걸치면 조각을 받아 이어 붙인다."""
    if is_local(url):
        cut_local(Path(url), segs[0][1], segs[-1][2], out, height)
        return
    pieces = []
    for i, (pn, ls, le) in enumerate(segs):
        stem = out.stem if len(segs) == 1 else f"{out.stem}_piece{i + 1}"
        cmd = [*YTDLP, "--no-warnings", "-N", "8",
               "-f", f"bv*[height<={height}]+ba/b[height<={height}]/b",
               "--merge-output-format", "mp4", "--concat-playlist", "never",
               "--download-sections", f"*{ls:.0f}-{le:.0f}",
               "-o", str(out.parent / f"{stem}.%(ext)s")]
        if pn:
            cmd += ["--playlist-items", str(pn)]
        run_live(cmd + [url])
        pieces.append(out.parent / f"{stem}.mp4")
    if len(pieces) == 1 and pieces[0].exists():
        faststart(pieces[0])
    if len(pieces) > 1:
        lst = out.parent / f"{out.stem}_pieces.txt"
        lst.write_text("".join(f"file '{x.name}'\n" for x in pieces))
        ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])
        for x in pieces:
            x.unlink()
        lst.unlink()


def cut_from_scan(vdir: Path, a: float, b: float, out: Path) -> bool:
    """판 찾기 때 받아 둔 저화질 전체 영상(scan/)에서 구간을 잘라 쓴다. 다시 받지 않아도 돼서 빠르다."""
    meta = vdir / "scan" / "scan.json"
    if not meta.exists():
        return False
    for p in json.loads(meta.read_text()).get("parts", []):
        src = vdir / "scan" / p.get("file", "")
        ps = float(p.get("start", 0))
        if src.exists() and ps <= a and b <= ps + float(p.get("duration", 0)):
            if not stream_info(src)["audio"]:
                return False
            ffmpeg(["-ss", f"{a - ps:.3f}", "-to", f"{b - ps:.3f}", "-i", str(src), "-c", "copy", "-movflags", "+faststart", str(out)])
            return out.exists()
    return False


def extract_reviews(url: str, vdir: Path, info: dict, gdir: Path, name: str, skip_transcribe: bool) -> list[dict]:
    """games.json에 적힌 이 판의 리플레이 피드백 구간을 받아 review/에 자료를 만든다."""
    games_json = vdir / "games.json"
    if not games_json.exists():
        return []
    entry = next((g for g in json.loads(games_json.read_text()).get("games", []) if f"game{g.get('n')}" == name), None)
    reviews = [r for r in (entry or {}).get("reviews") or [] if r.get("from") and r.get("to")]
    rdir = gdir / "review"
    want = [[round(parse_time(r["from"])), round(parse_time(r["to"]))] for r in reviews]
    have = json.loads((rdir / "review.json").read_text()) if (rdir / "review.json").exists() else None
    if have != want:
        shutil.rmtree(rdir, ignore_errors=True)
    if not reviews:
        return []
    (rdir / "frames").mkdir(parents=True, exist_ok=True)
    (rdir / "sheets").mkdir(exist_ok=True)
    out = []
    for i, (a, b) in enumerate(want, 1):
        video = rdir / f"seg{i}.mp4"
        if not video.exists():
            print(f"리플레이 피드백 구간 {i}: {hms(a)} ~ {hms(b)}", flush=True)
            # 리플레이는 인게임 시계와 장면만 읽으면 돼서 저화질로 충분하다. 스캔 영상이 있으면 거기서 자른다
            if is_local(url) or not cut_from_scan(vdir, a, b, video):
                download(url, locate(vdir, info, a, b), video, 720)
        if not video.exists():
            print(f"리플레이 구간 {i} 다운로드 실패, 건너뜀", flush=True)
            continue
        if not list((rdir / "frames").glob(f"{hms(a).replace(':', '-')}*.jpg")):
            tmp = rdir / f"_tmp{i}"
            tmp.mkdir(exist_ok=True)
            ffmpeg(["-i", str(video), "-vf", f"fps=1/5,scale=1280:-2,{drawtext_clock(a, 26)}",
                    "-q:v", "3", str(tmp / "%05d.jpg")])
            for k, f in enumerate(sorted(tmp.glob("*.jpg"))):
                f.rename(rdir / "frames" / (hms(a + k * 5).replace(":", "-") + ".jpg"))
            shutil.rmtree(tmp)
            # 20초 간격 4x3 = 4분짜리 시트
            ffmpeg(["-i", str(video), "-vf", f"fps=1/20,scale=480:-2,{drawtext_clock(a, 22)},tile=4x3",
                    "-q:v", "4", str(rdir / "sheets" / f"s{i}_%03d.jpg")])
        if not skip_transcribe:
            transcribe_review(rdir, i, a)
        sheets = sorted(rdir.joinpath("sheets").glob(f"s{i}_*.jpg"))
        out.append({"from": hms(a), "to": hms(b), "note": reviews[i - 1].get("note"),
                    "sheets": [{"file": f"review/sheets/{f.name}", "from": hms(a + k * 240),
                                "to": hms(min(a + (k + 1) * 240, b))} for k, f in enumerate(sheets)]})
    join_review_transcripts(rdir, out)
    (rdir / "review.json").write_text(json.dumps(want))
    return out


def transcribe_review(rdir: Path, i: int, a: float) -> None:
    md, video = rdir / f"seg{i}.md", rdir / f"seg{i}.mp4"
    if md.exists() or not video.exists():
        return
    audio = rdir / f"seg{i}.m4a"
    ffmpeg(["-i", str(video), "-vn", "-c:a", "copy", str(audio)])
    transcribe(audio, a, md, rdir / f"seg{i}.json")


def join_review_transcripts(rdir: Path, reviews: list[dict]) -> None:
    """구간별 받아쓰기를 하나로"""
    parts = [f"## 리플레이 구간 {i} ({r['from']} ~ {r['to']})\n" + (rdir / f"seg{i}.md").read_text()
             for i, r in enumerate(reviews, 1) if (rdir / f"seg{i}.md").exists()]
    if parts:
        (rdir / "transcript.md").write_text("\n".join(parts))


def build_images(gdir: Path, video: Path, start: float, vstart: float, game_off: float, game_dur: float,
                 draft_start: float | None, crop: str, x: float, y: float, w: float, h: float,
                 frame_interval: int, minimap_interval: int) -> None:
    for sub in ("frames", "minimap", "overview"):
        d = gdir / sub
        d.mkdir(exist_ok=True)
        for old in d.glob("*.jpg"):
            old.unlink()
    # 키프레임이 2초 안팎으로 촘촘하면 키프레임만 디코딩한다. 5초 간격 프레임에는 이걸로 충분하고 4배쯤 빠르다
    fast = ["-skip_frame", "nokey"] if keyframe_gap(video) <= 2.5 else []
    # 한 번 디코딩해서 세 종류를 같이 만든다
    #   frames/   5초 간격 전체 화면 (파일명 = VOD 시각)
    #   minimap/  5초 간격 미니맵 시트 6x5칸. 아이콘이 작아서 원본 해상도 그대로 자른다
    #   overview/ 30초 간격 4x4 = 8분 흐름 시트
    graph = (
        "[0:v]split=3[a][b][c];"
        f"[a]fps=1/{frame_interval},scale=1280:-2,{drawtext_clock(start, 26)}[fa];"
        f"[b]fps=1/{minimap_interval},{crop},{drawtext_clock(start, 20)},tile=6x5[fb];"
        f"[c]fps=1/30,scale=480:-2,{drawtext_clock(start, 22)},tile=4x4[fc]"
    )
    ffmpeg([*fast, "-ss", f"{game_off:.3f}", "-i", str(video), "-filter_complex", graph,
            "-map", "[fa]", "-q:v", "3", str(gdir / "frames" / "%05d.jpg"),
            "-map", "[fb]", "-q:v", "3", str(gdir / "minimap" / "sheet_%03d.jpg"),
            "-map", "[fc]", "-q:v", "4", str(gdir / "overview" / "sheet_%03d.jpg")])
    for i, f in enumerate(sorted((gdir / "frames").glob("*.jpg"))):
        f.rename(f.with_name(hms(start + i * frame_interval).replace(":", "-") + ".jpg"))

    # 밴픽: 픽창 구간을 2초 간격 원본 해상도로 (밴, 픽 순서, 룬, 스펠 글씨를 읽어야 해서)
    if draft_start is not None:
        ddir = gdir / "draft"
        (ddir / "frames").mkdir(parents=True, exist_ok=True)
        for old in list((ddir / "frames").glob("*.jpg")) + list(ddir.glob("sheet_*.jpg")):
            old.unlink()
        # 4초 간격 4x3 = 48초짜리 시트로 픽창 흐름 훑기
        ffmpeg([*fast, "-t", f"{game_off:.3f}", "-i", str(video), "-filter_complex",
                f"[0:v]split=2[a][b];[a]fps=1/2,{drawtext_clock(vstart, 30)}[fa];"
                f"[b]fps=1/4,scale=640:-2,{drawtext_clock(vstart, 20)},tile=4x3[fb]",
                "-map", "[fa]", "-q:v", "2", str(ddir / "frames" / "%05d.jpg"),
                "-map", "[fb]", "-q:v", "3", str(ddir / "sheet_%03d.jpg")])
        for i, f in enumerate(sorted((ddir / "frames").glob("*.jpg"))):
            f.rename(f.with_name(hms(vstart + i * 2).replace(":", "-") + ".jpg"))

    # 미니맵 자르기 영역 확인용
    ffmpeg(["-ss", f"{game_off + min(game_dur / 2, 600):.0f}", "-i", str(video), "-frames:v", "1", "-vf",
            f"drawbox=x=iw*{x}:y=ih*{y}:w=iw*{w}:h=ih*{h}:color=red:t=4,scale=1280:-2",
            str(gdir / "minimap_check.jpg")])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--draft-start", help="픽창 시작 시각 (전체 VOD 시각)")
    ap.add_argument("--start", required=True, help="게임 시작 시각 (전체 VOD 시각), 예: 1:23:00")
    ap.add_argument("--end", required=True)
    ap.add_argument("--name", required=True, help="판 이름, 예: game2")
    ap.add_argument("--frame-interval", type=int, default=5)
    ap.add_argument("--minimap-interval", type=int, default=5, help="미니맵 시트 간격(초)")
    ap.add_argument("--minimap", default="0.82,0.68,0.18,0.32",
                    help="미니맵 영역 x,y,w,h (화면 대비 비율). minimap_check.jpg 보고 조정")
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--skip-transcribe", action="store_true")
    ap.add_argument("--redo-images", action="store_true", help="영상은 그대로 두고 이미지만 다시 생성")
    args = ap.parse_args()
    require_tools()

    start, end = parse_time(args.start), parse_time(args.end)
    if end <= start:
        die("--end가 --start보다 커야 합니다")
    vdir, info = find_vod_dir(args.url)
    gdir = vdir / args.name
    gdir.mkdir(parents=True, exist_ok=True)
    draft_start = parse_time(args.draft_start) if args.draft_start else None
    if draft_start is not None and draft_start >= start:
        die("--draft-start는 --start보다 앞이어야 합니다")
    vstart = draft_start if draft_start is not None else start  # 받은 영상의 첫 프레임 = VOD 시각 vstart
    game_off = start - vstart  # 영상 안에서 게임이 시작하는 위치(초)
    segs = locate(vdir, info, vstart, end)
    part = segs[0][0] if len(segs) == 1 else [g[0] for g in segs]

    video = gdir / "video.mp4"
    vinfo_path = gdir / "video.json"  # 받은 영상이 VOD의 어느 구간인지 기록
    want = {"vstart": round(vstart), "end": round(end)}
    if video.exists():
        have = json.loads(vinfo_path.read_text()) if vinfo_path.exists() else None
        short = probe_duration(video) < (end - vstart) - 60  # 파트 경계에서 잘린 영상
        if have != want or short:
            # 구간이 다르거나 기록이 없는 영상: 시각이 어긋나므로 영상과 거기서 만든 자료를 모두 다시 만든다
            why = "중간에 잘려 있어서" if have == want else f"구간({have})이 요청({want})과 달라서"
            print(f"받아 둔 영상이 {why} 다시 받습니다", flush=True)
            for name in ("video.mp4", "video.json", "audio.m4a", "transcript.md", "transcript.json", "fight_candidates.md",
                         "minimap_check.jpg", "game.json"):
                (gdir / name).unlink(missing_ok=True)
            for sub in ("frames", "minimap", "overview", "draft", "zoom"):
                shutil.rmtree(gdir / sub, ignore_errors=True)
    if not video.exists():
        download(args.url, segs, video, args.height)
    if not video.exists():
        die("구간 다운로드 실패")
    if probe_duration(video) < (end - vstart) - 60:
        print(f"주의: 받은 영상({hms(probe_duration(video))})이 요청 구간({hms(end - vstart)})보다 짧아요", flush=True)
    if not vinfo_path.exists():
        vinfo_path.write_text(json.dumps(want))
    dur = probe_duration(video)
    game_dur = dur - game_off
    game_in = ["-ss", f"{game_off:.3f}", "-i", str(video)]

    x, y, w, h = (float(v) for v in args.minimap.split(","))
    crop = f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"

    # 예전 설정(미니맵 10초 간격 등)으로 만든 이미지면 다시 만든다
    old_meta = json.loads((gdir / "game.json").read_text()) if (gdir / "game.json").exists() else {}
    stale = bool(old_meta) and old_meta.get("minimap_interval") != args.minimap_interval
    make_images = args.redo_images or stale or not (gdir / "frames").exists()
    # 받아쓰기(GPU)와 이미지 만들기(CPU)를 동시에 돌린다
    images = Background(build_images, gdir, video, start, vstart, game_off, game_dur, draft_start, crop, x, y, w, h,
                        args.frame_interval, args.minimap_interval) if make_images else None
    if images:
        images.start()
    # 5초 간격이 놓친 상대 챔피언 등장(1초마다 미니맵 확인)도 동시에
    from sightings import build as build_sightings
    sightings = Background(build_sightings, gdir, video, start, game_off, args.minimap, args.minimap_interval)
    sightings.start()
    # 리플레이 피드백 영상도 동시에 준비한다(받아쓰기는 아래에서 차례로)
    reviews_job = Background(extract_reviews, args.url, vdir, info, gdir, args.name, True)
    reviews_job.start()

    if not args.skip_transcribe and not (gdir / "transcript.md").exists() and not stream_info(video)["audio"]:
        # 소리 없이 녹화한 내 게임: 받아쓰기 없이 화면과 게임 기록(live.json)으로 분석한다
        (gdir / "transcript.md").write_text("(녹음 없음)\n")
        (gdir / "transcript.json").write_text("[]")
    if not args.skip_transcribe and not (gdir / "transcript.md").exists():
        audio = gdir / "audio.m4a"
        if not audio.exists():
            # 다시 인코딩하지 않고 소리만 꺼낸다(몇 초)
            ffmpeg(["-i", str(video), "-vn", "-c:a", "copy", str(audio)])
        transcribe(audio, vstart, gdir / "transcript.md", gdir / "transcript.json")

    reviews = reviews_job.join_or_raise()
    if not args.skip_transcribe and reviews:
        rdir = gdir / "review"
        for i, r in enumerate(reviews, 1):
            transcribe_review(rdir, i, parse_time(r["from"]))
        join_review_transcripts(rdir, reviews)
    if images:
        images.join_or_raise()
    try:
        sighting_sheets = sightings.join_or_raise()
    except Exception as e:  # noqa: BLE001  보조 자료라 실패해도 분석은 한다
        print(f"상대 등장 찾기 실패, 건너뜀: {e}", flush=True)
        sighting_sheets = []

    def ranges(sub: str, span: int) -> list[dict]:
        out = []
        for i, f in enumerate(sorted((gdir / sub).glob("sheet_*.jpg"))):
            out.append({"file": f"{sub}/{f.name}", "from": hms(start + i * span),
                        "to": hms(min(start + (i + 1) * span, start + game_dur))})
        return out

    manifest = {
        "url": args.url, "name": args.name,
        "draft_start": hms(draft_start) if draft_start is not None else None,
        "video_start": hms(vstart), "start": hms(start), "end": hms(vstart + dur),
        "part": part, "minimap_crop": args.minimap, "minimap_interval": args.minimap_interval, "frame_interval": args.frame_interval,
        "minimap_sheets": ranges("minimap", 30 * args.minimap_interval), "overview_sheets": ranges("overview", 480),
        "sighting_sheets": sighting_sheets,
        "reviews": reviews,
        "note": "구간 다운로드는 키프레임 기준이라 VOD 시각이 몇 초 어긋날 수 있다. 정확한 시각은 화면의 인게임 시계를 따른다.",
    }
    (gdir / "game.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))

    from fights import find as find_fights
    find_fights(gdir)

    print(f"\n완료 → {gdir}")
    if draft_start is not None:
        print(f"  픽창 프레임 {len(list((gdir / 'draft' / 'frames').glob('*.jpg')))}장 ({hms(draft_start)} ~ {hms(start)})")
    print(f"  프레임 {len(list((gdir / 'frames').glob('*.jpg')))}장, "
          f"미니맵 시트 {len(manifest['minimap_sheets'])}장, 흐름 시트 {len(manifest['overview_sheets'])}장")
    if reviews:
        print(f"  리플레이 피드백 {len(reviews)}구간 → review/")


if __name__ == "__main__":
    main()
