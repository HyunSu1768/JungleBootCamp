#!/usr/bin/env python3
"""분석 결과에서 번역투 롤 용어를 찾아 한국 롤 유저가 쓰는 말로 바꾼다.

    uv run tools/terms.py vods/<vod>/<game>          # 검사만 (찾으면 종료 코드 1)
    uv run tools/terms.py vods/<vod>/<game> --fix    # 확실한 것만 바꾸고, 나머지는 목록으로

analysis.json과, kb/*.json에서 이 판(game_ref)에서 나온 항목을 본다.
발언 원문(quote, said, plan_quote)과 이미지 경로는 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VODS = Path(os.environ.get("JUNGLE_VODS", ROOT / "vods"))
KB = Path(os.environ.get("JUNGLE_KB", ROOT / "kb"))

# (찾을 패턴, 바꿀 말 또는 None, 설명). None이면 문맥을 봐야 해서 목록에만 띄운다.
TERMS: list[tuple[str, str | None, str]] = [
    (r"플렉스\s*픽", "조커픽", "조커픽"),
    (r"플렉스", "조커픽", "조커픽"),
    (r"리치(?=[가는를와의도로이] |\s|$|[,.·)])", "사거리", "사거리"),
    (r"진입 담당", "이니시 담당", "이니시 담당"),
    (r"진입 조합", "돌진 조합", "돌진 조합"),
    (r"선취점", "퍼블", "퍼블"),
    (r"보호기", "실드", "실드"),
    (r"(?<![A-Za-z0-9])R로(?![A-Za-z0-9])", "궁으로", "궁"),
    (r"(?<![A-Za-z0-9])R(?![A-Za-z0-9])", "궁", "궁 (Q, W, E는 그대로 써도 돼요)"),
    (r"인게이지|엔게이지", "이니시", "이니시"),
    (r"디스인게이지", None, "받아치기, 빠지기"),
    (r"트레이드", None, "딜교, 교환"),
    (r"피킹|픽오프", None, "끊기, 자르기"),
    (r"프레셔", "압박", "압박"),
    (r"스케일링", None, "후반 밸류, 성장 곡선"),
    (r"컨테스트", None, "견제, 싸움 걸기, 비비기"),
    (r"쓰레트|스레트", "위협", "위협"),
    (r"크로스맵", "반대편 교환", "반대편 교환"),
    (r"로테이션", None, "동선, 합류"),
    (r"셋업", None, "각 만들기, 판 깔기"),
    (r"레버리지", None, "이득, 주도권"),
    (r"(?<!\d)\d{1,3}:\d{1,3}(?=로 밀|으로 밀|로 앞|으로 앞| 우세| 열세)", None, "CS나 킬은 'CS 25대37'처럼 무엇의 숫자인지 붙여서"),
    # 킬 스코어를 시각처럼 쓴 것: "9:7까지", "1:4가", "15:24로"
    (r"(?<!킬 )(?<!\d)\d{1,2}:\d{1,2}(?=로 뒤|으로 뒤|가 됐|이 됐|가 되|이 되|이던|였던| 동률|까지 갔|까지 벌|까지 따라)", None,
     "킬 스코어는 '킬 9대7'처럼 (게임 시각과 헷갈림)"),
]

# 바꾼 말의 받침에 맞게 조사를 고친다 (플렉스로 → 조커픽으로, 선취점을 → 퍼블을)
PARTICLES: list[tuple[str, str]] = [
    (r"조커픽로", "조커픽으로"), (r"조커픽가", "조커픽이"), (r"조커픽는", "조커픽은"), (r"조커픽라", "조커픽이라"),
    (r"조커픽를", "조커픽을"), (r"조커픽와", "조커픽과"),
    (r"퍼블이(?=[^가-힣]|$| )", "퍼블이"), (r"퍼블을", "퍼블을"), (r"퍼블으로", "퍼블로"), (r"퍼블과", "퍼블과"),
    (r"이니시가", "이니시가"),
]


def fix_particles(x: str) -> str:
    for pat, rep in PARTICLES:
        x = re.sub(pat, rep, x)
    return x


SKIP_KEYS = {"quote", "said", "plan_quote", "frames", "image", "file", "game_ref", "ref", "scene", "id",
             "ingame", "vod", "from", "to", "t", "spawn", "prep_from", "range", "length"}


def walk(x, path: str, fix: bool, found: list):
    if isinstance(x, dict):
        return {k: (v if k in SKIP_KEYS else walk(v, f"{path}.{k}", fix, found)) for k, v in x.items()}
    if isinstance(x, list):
        return [walk(v, f"{path}[{i}]", fix, found) for i, v in enumerate(x)]
    if isinstance(x, str):
        for pat, rep, hint in TERMS:
            for m in re.finditer(pat, x):
                found.append((path, m.group(0), rep, hint, x))
            if fix and rep is not None:
                x = re.sub(pat, rep, x)
        return fix_particles(x) if fix else x
    return x


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("game_dir")
    ap.add_argument("--fix", action="store_true")
    args = ap.parse_args()
    gdir = Path(args.game_dir).resolve()
    game_ref = f"{gdir.parent.name}/{gdir.name}"

    targets: list[tuple[Path, str]] = [(gdir / "analysis.json", "analysis")]
    for name in ("concepts", "rules", "quizzes"):
        targets.append((KB / f"{name}.json", name))

    left = []
    for path, label in targets:
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        found: list = []
        if label == "analysis":
            new = walk(data, label, args.fix, found)
        else:
            new = []
            for item in data:
                refs = json.dumps(item, ensure_ascii=False)
                if game_ref in refs:
                    new.append(walk(item, f"{label}:{item.get('id')}", args.fix, found))
                else:
                    new.append(item)
        if args.fix and new != data:
            path.write_text(json.dumps(new, ensure_ascii=False, indent=1))
        for p, word, rep, hint, text in found:
            if args.fix and rep is not None:
                continue
            left.append(f"- {p}: '{word}' → {hint}\n    {text[:120]}")
        if args.fix:
            fixed = sum(1 for f in found if f[2] is not None)
            if fixed:
                print(f"{path.name}: {fixed}곳 바꿈")

    if left:
        print(f"직접 고쳐야 할 표현 {len(left)}곳 (문맥 보고 한국 롤 유저가 쓰는 말로):")
        print("\n".join(left))
        sys.exit(1)
    print("번역투 용어 없음")


if __name__ == "__main__":
    main()
