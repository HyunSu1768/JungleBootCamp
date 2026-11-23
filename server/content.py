"""앱에 같이 들어온 공유 콘텐츠(content/)를 사용자 데이터에 합친다.

릴리스에는 개발자가 분석한 프로 판(tools/export_content.py)과 kb/가 들어 있다. 앱을 켤 때마다:
- 프로 판: 없는 파일은 넣는다. 사용자가 그 판을 다시 분석했으면(파일이 우리가 넣은 것과 다르면) 건드리지 않는다.
  새 버전에서 공유 분석이 바뀌었고 사용자가 손대지 않았으면 새 것으로 바꾼다.
- kb: 같은 id는 사용자 것을 두고 근거, 사례 목록만 합친다. 새 id는 넣는다.
어느 파일을 우리가 넣었는지는 VODS/_shared.json에 해시로 기록한다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .jobs import KB, ROOT, VODS

CONTENT = ROOT / "content"
SEEDED = VODS / "_shared.json"
LIST_FIELDS = ("evidence", "examples", "exceptions", "criteria", "concepts", "cases")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _read(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def seed_vods() -> int:
    manifest = _read(CONTENT / "manifest.json", None)
    if not manifest or CONTENT.resolve() == VODS.resolve():
        return 0
    seeded: dict[str, str] = _read(SEEDED, {})
    n = 0
    for rel, h in manifest["files"].items():
        src, dst = CONTENT / "vods" / rel, VODS / rel
        if not src.exists():
            continue
        if dst.exists():
            cur = _sha(dst)
            if cur == h:
                seeded[rel] = h
                continue
            if seeded.get(rel) != cur:
                continue  # 사용자가 다시 분석했거나 직접 만든 파일
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.copy2(src, tmp)
        tmp.replace(dst)
        seeded[rel] = h
        n += 1
    VODS.mkdir(parents=True, exist_ok=True)
    SEEDED.write_text(json.dumps(seeded, ensure_ascii=False))
    return n


def _key(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def merge_kb() -> int:
    src_dir = CONTENT.parent / "kb"
    if src_dir.resolve() == KB.resolve() or not src_dir.exists():
        return 0  # 개발 중(저장소의 kb를 그대로 씀)
    KB.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in ("concepts.json", "rules.json", "quizzes.json"):
        shared = _read(src_dir / name, None)
        if not isinstance(shared, list):
            continue
        mine = _read(KB / name, [])
        if not isinstance(mine, list):
            mine = []
        by_id = {x.get("id"): x for x in mine if isinstance(x, dict)}
        changed = False
        for item in shared:
            cur = by_id.get(item.get("id"))
            if cur is None:
                mine.append(item)
                by_id[item.get("id")] = item
                changed = True
                n += 1
                continue
            for f in LIST_FIELDS:  # 새 버전에서 늘어난 근거, 사례
                if isinstance(item.get(f), list) and isinstance(cur.get(f), list):
                    have = {_key(x) for x in cur[f]}
                    for x in item[f]:
                        if _key(x) not in have:
                            cur[f].append(x)
                            changed = True
        if changed:
            tmp = KB / (name + ".tmp")
            tmp.write_text(json.dumps(mine, ensure_ascii=False, indent=1))
            tmp.replace(KB / name)
    return n


def seed() -> dict:
    return {"files": seed_vods(), "kb": merge_kb()}
