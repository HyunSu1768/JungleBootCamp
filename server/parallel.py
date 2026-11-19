"""한 판 분석을 여러 Claude가 동시에 나눠 하고, 결과 조각을 합친다.

한 Claude가 분석 전체(100KB 넘는 JSON)를 혼자 쓰면 15~20분이 걸린다. 대부분 글을 쓰는 시간이라,
플랜 / 시간대별 턴 / 운영·교전·피드백으로 나눠 동시에 쓰게 하면 가장 긴 담당의 시간만큼만 걸린다.
담당별 규칙은 `.claude/skills/jungle-vod/SKILL.md`의 'D. 나눠서 분석하기'.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

INF = 10 ** 6


@dataclass
class Worker:
    name: str     # parts/<name>.json
    label: str    # 진행 로그에 붙는 이름
    task: str     # 프롬프트에 들어가는 담당 설명
    keys: list[str]


def secs(t) -> float | None:
    """'12:30', '1:02:03' → 초. 못 읽으면 None"""
    if t is None:
        return None
    m = re.match(r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}))?", str(t))
    if not m:
        return None
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c is not None else int(a) * 60 + int(b)


def mmss(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def game_minutes(gdir: Path) -> float:
    """인게임 길이(분). 게임 화면이 처음 보인 시각부터 끝까지라 실제보다 조금 짧거나 길 수 있다"""
    meta = json.loads((gdir / "game.json").read_text())
    s, e = secs(meta.get("start")), secs(meta.get("end"))
    return (e - s) / 60 if s is not None and e is not None and e > s else 30.0


def windows(minutes: float) -> list[tuple[int, int]]:
    """턴 담당 구간(인게임 분). 담당 하나가 쓰는 분량이 시간을 정해서 6~7분 단위로 나눈다.
    마지막 구간이 3분도 안 남으면 앞 구간에 붙인다"""
    cuts = [c for c in (0, 6, 12, 18, 25, 32) if c == 0 or c < minutes - 3]
    return list(zip(cuts, cuts[1:] + [INF]))


def materials(gdir: Path, a: float, b: float) -> str:
    """인게임 a~b초를 보려면 열 자료. 인게임 0:00 ≈ 게임 화면이 처음 보인 VOD 시각(담당이 시계로 확인한다)"""
    meta = json.loads((gdir / "game.json").read_text())
    start = secs(meta.get("start")) or 0
    lo, hi = start + a - 60, start + min(b, 4 * 3600) + 60

    def overlap(sh: dict) -> bool:
        f, t = secs(sh.get("from")), secs(sh.get("to"))
        return f is not None and t is not None and f < hi and t > lo

    mm = [sh["file"] for sh in meta.get("minimap_sheets") or [] if overlap(sh)]
    sight = []
    for sh in meta.get("sighting_sheets") or []:
        ts = [t for t in sh.get("times") or [] if lo <= (secs(t) or -1) <= hi]
        if ts:
            sight.append(f"{sh['file']} ({', '.join(ts)})")
    def vod(x: float) -> str:
        x = int(x)
        return f"{x // 3600}:{x % 3600 // 60:02d}:{x % 60:02d}"
    parts = [f"VOD {vod(max(lo, start))} ~ {vod(hi) if b < INF else '끝'} 근처"]
    if mm:
        parts.append("미니맵 시트 " + ", ".join(mm))
    if sight:
        parts.append("5초 간격이 놓친 상대 등장 " + "; ".join(sight) + " — 상대 정글 동선에 꼭 반영")
    return ". ".join(parts) + ". 원본 프레임은 `frames/` (파일명 = VOD 시각)."


def turn_worker(gdir: Path, name: str, prefix: str, a: float, b: float) -> Worker:
    """인게임 a~b초에 시작하는 턴 담당"""
    def mm(x: float) -> str:
        return f"{int(x) // 60}:{int(x) % 60:02d}"
    rng = f"인게임 {mm(a)} 이후" if b >= INF else f"인게임 {mm(a)} ~ {mm(b)}"
    label = (f"턴 {int(a // 60)}분~" if b >= INF else f"턴 {int(a // 60)}~{int(round(b / 60))}분") if a % 60 == 0 else f"빈 턴 {mm(a)}"
    return Worker(
        name, label,
        f"턴 담당: {rng}에 시작하는 턴(우리 정글 ally, 상대 정글 enemy). "
        "구간 안의 귀환과 사망을 하나도 빠뜨리지 말고 턴을 나눠. 턴 사이는 귀환해서 다시 나오거나 죽어서 부활하는 시간 말고는 비면 안 돼. "
        f"id 접두사는 `{prefix}` (턴 {prefix}t1, 판단 {prefix}t1-d1, 상대 턴 {prefix}e1). "
        f"볼 자료: {materials(gdir, a, b)}",
        ["ally", "enemy"])


def workers(gdir: Path, mode: str) -> list[Worker]:
    """mode: 'pro'(B. 프로 판) | 'mine'(C. 내 게임)"""
    out = [Worker("plan", "플랜", "플랜 담당: 1층 플랜.", ["streamer", "champion", "enemy_jungler", "context", "plan"])]
    for k, (a, b) in enumerate(windows(game_minutes(gdir)), 1):
        out.append(turn_worker(gdir, f"turns-{k}", f"w{k}", a * 60, b * 60 if b < INF else INF))
    ops_keys = ["result", "length", "summary", "takeaways", "pattern", "operations"]
    ops_keys += [] if mode == "pro" else ["goal_check", "next_goal"]
    out.append(Worker("flow", "운영", "운영 담당: 3층 운영, 판 전체 요약, 턴 운영 방식"
                      + ("" if mode == "pro" else ", 목표 판정과 다음 목표") + ".", ops_keys))
    out.append(Worker("fights", "교전" + ("·피드백" if mode == "pro" else ""),
                      "교전 담당: 중요한 교전 2~5개(확대 포함)" + (", 리플레이 피드백" if mode == "pro" else "") + ".",
                      ["fights", "review"] if mode == "pro" else ["fights"]))
    return out


def prompt(w: Worker, gdir: Path, mode: str, vods: Path, kb: Path, extra: str = "") -> str:
    section = "B. 판 분석" if mode == "pro" else "C. 내 게임 분석"
    part = gdir / "parts" / f"{w.name}.json"
    return (
        f"`.claude/skills/jungle-vod/SKILL.md`와 `SCHEMA.md`를 읽어. 이 판은 여러 명이 담당을 나눠 동시에 분석하고 있어. "
        f"너는 '{w.label}' 담당이야. SKILL.md의 'D. 나눠서 분석하기'와 '{section}'을 따르되 네 담당만 해.\n"
        f"- 게임 폴더: `{gdir}`\n"
        f"- 담당: {w.task}\n"
        f"- 결과: `{part}`에 이 키만 담은 JSON 객체로 써: {', '.join(w.keys)}\n"
        f"- 원칙 `{kb}/rules.json`, 개념 `{kb}/concepts.json`은 읽기만 해. `analysis.json`과 `kb/`는 쓰지 마.\n"
        f"- 처음부터 화면(프레임, 시트)과 받아쓰기로 분석해. 이 판의 예전 분석이나 다른 담당의 조각(`parts/`)은 열지 마.\n"
        f"- 이미지 경로는 `{vods}` 기준 상대 경로로 써.\n"
        + (f"- {extra}\n" if extra else "")
        + "사용자에게 질문하지 말고 끝까지 진행해. 마지막 답변은 한국어 한 줄로."
    )


def load_part(gdir: Path, w: Worker) -> dict:
    """조각을 읽어 담당 키만 남긴다. 없거나 깨졌으면 예외"""
    path = gdir / "parts" / f"{w.name}.json"
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: JSON 객체가 아니에요")
    missing = [k for k in w.keys if k not in data and k not in ("goal_check",)]
    if missing:
        raise ValueError(f"{path.name}: {', '.join(missing)} 없음")
    return {k: data[k] for k in w.keys if k in data}


def gaps(gdir: Path, ws: list[Worker], minutes: float) -> list[tuple[float, float]]:
    """턴 조각을 합쳐 봤을 때 비는 구간(인게임 초). 담당이 턴을 건너뛰면 채우려고 쓴다"""
    turns = []
    for w in ws:
        if w.name.startswith("turns-"):
            try:
                turns += load_part(gdir, w).get("ally") or []
            except Exception:  # noqa: BLE001
                pass
    spans = sorted(_turn_span(t) + (str(t.get("end") or ""),) for t in turns if _turn_span(t)[0] < INF)
    out = []
    end_of_game = minutes * 60
    prev_end, prev_kind = 90.0, "시작"  # 첫 턴은 1:30 전후에 시작한다
    for a, b, kind in spans:
        # 사망이면 부활 시간(후반 최대 1분 넘게)을 봐 준다. 귀환이면 다시 나오기까지 30초 안팎
        allow = 100 if "사망" in prev_kind else 60
        if a - prev_end > allow:
            out.append((prev_end, a))
        if b > prev_end:
            prev_end, prev_kind = b, kind
    if end_of_game - prev_end > 120 and "끝" not in prev_kind:
        out.append((prev_end, end_of_game))
    return out


def _turn_span(t: dict) -> tuple[float, float]:
    a = secs(t.get("from"))
    b = secs(t.get("to"))
    a = a if a is not None else INF
    return a, (b if b is not None and b >= a else a)


def merge(gdir: Path, ws: list[Worker], mode: str) -> dict:
    parts = {w.name: load_part(gdir, w) for w in ws}
    plan, flow = parts["plan"], {**parts["flow"], **parts.get("fights", {})}

    ally, enemy = [], []
    for w in ws:
        if w.name.startswith("turns-"):
            ally += parts[w.name].get("ally") or []
            enemy += parts[w.name].get("enemy") or []
    ally.sort(key=lambda t: _turn_span(t)[0])
    enemy.sort(key=lambda t: _turn_span(t)[0])

    # 담당별 임시 id(w2t1)를 판 전체 순서(t1, t2...)로 다시 매긴다
    remap: dict[str, str] = {}
    for i, t in enumerate(ally, 1):
        old, new = str(t.get("id") or ""), f"t{i}"
        remap[old] = new
        t["id"] = new
        for j, d in enumerate(t.get("decisions") or [], 1):
            remap[str(d.get("id") or "")] = f"{new}-d{j}"
            d["id"] = f"{new}-d{j}"
    for i, e in enumerate(enemy, 1):
        remap[str(e.get("id") or "")] = f"e{i}"
        e["id"] = f"e{i}"

    def turn_at(sec: float) -> str | None:
        best, gap = None, INF
        for t in ally:
            a, b = _turn_span(t)
            if a <= sec <= b:
                return t["id"]
            d = min(abs(sec - a), abs(sec - b))
            if d < gap:
                best, gap = t["id"], d
        return best if gap <= 90 else None

    def fix_ref(r):
        r = str(r)
        if r.startswith("@"):
            s = secs(r[1:])
            return turn_at(s) if s is not None else None
        return remap.get(r, r)

    review = flow.get("review")
    if isinstance(review, dict):
        for c in review.get("comments") or []:
            c["refs"] = [x for x in (fix_ref(r) for r in c.get("refs") or []) if x]

    a = {
        "version": 2,
        "streamer": plan.get("streamer"),
        "champion": plan.get("champion"),
        "enemy_jungler": plan.get("enemy_jungler"),
        "result": flow.get("result"),
        "length": flow.get("length"),
        "context": plan.get("context"),
    }
    if mode == "mine":
        a["own"] = True
        a["streamer"] = None
    a.update({
        "summary": flow.get("summary") or [],
        "takeaways": flow.get("takeaways") or [],
        "plan": plan.get("plan") or {},
        "turns": {"ally": ally, "enemy": enemy, "pattern": flow.get("pattern") or ""},
        "operations": flow.get("operations") or {},
        "fights": flow.get("fights") or [],
        "review": review if mode == "pro" and review else {"available": False},
        "new_concepts": [], "new_rules": [], "new_quizzes": [],
    })
    if mode == "mine":
        for k in ("goal_check", "next_goal"):
            if flow.get(k):
                a[k] = flow[k]
    return a
