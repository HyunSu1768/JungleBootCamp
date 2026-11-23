"""한 판을 담당별로 나눠 분석한 조각 합치기"""

import json

from server import parallel


def _game(tmp_path, minutes=26):
    g = tmp_path / "game1"
    (g / "parts").mkdir(parents=True)
    (g / "game.json").write_text(json.dumps({"start": "1:00:00", "end": f"1:{minutes:02d}:00"}))
    return g


def _write(g, name, data):
    (g / "parts" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False))


def test_windows_merge_short_tail():
    assert parallel.windows(26) == [(0, 6), (6, 12), (12, 18), (18, parallel.INF)]
    assert parallel.windows(20)[-1] == (12, parallel.INF)  # 18분 구간은 3분도 안 남아 앞에 붙는다


def test_merge_renumbers_and_resolves_time_refs(tmp_path):
    g = _game(tmp_path)
    ws = parallel.workers(g, "pro")
    _write(g, "plan", {"streamer": "s", "champion": "자르반 4세", "enemy_jungler": "아트록스", "context": "솔로랭크", "plan": {}})
    _write(g, "turns-2", {"ally": [{"id": "w2t1", "from": "6:10", "to": "8:00", "decisions": [{"id": "w2t1-d1"}]}], "enemy": []})
    _write(g, "turns-1", {"ally": [{"id": "w1t1", "from": "1:30", "to": "5:50", "decisions": [{"id": "w1t1-d1"}, {"id": "x"}]}],
                          "enemy": [{"id": "w1e1", "from": "1:30", "to": "4:00"}]})
    _write(g, "turns-3", {"ally": [], "enemy": []})
    _write(g, "turns-4", {"ally": [], "enemy": []})
    _write(g, "flow", {"result": "패", "length": "26:00", "summary": [], "takeaways": ["a"], "pattern": "", "operations": {}})
    _write(g, "fights", {"fights": [], "review": {"available": True, "comments": [{"refs": ["@7:00", "w1t1-d1"]}]}})
    a = parallel.merge(g, ws, "pro")
    ally = a["turns"]["ally"]
    assert [t["id"] for t in ally] == ["t1", "t2"]
    assert [d["id"] for d in ally[0]["decisions"]] == ["t1-d1", "t1-d2"]
    assert a["turns"]["enemy"][0]["id"] == "e1"
    assert a["review"]["comments"][0]["refs"] == ["t2", "t1-d1"]  # @7:00 → 그 시각의 턴


def test_gaps_finds_skipped_turn(tmp_path):
    g = _game(tmp_path)
    ws = parallel.workers(g, "pro")
    _write(g, "turns-1", {"ally": [{"id": "a", "from": "1:30", "to": "5:00", "end": "귀환"}], "enemy": []})
    _write(g, "turns-2", {"ally": [{"id": "b", "from": "5:20", "to": "11:00", "end": "귀환"}], "enemy": []})
    _write(g, "turns-3", {"ally": [{"id": "c", "from": "15:00", "to": "26:00", "end": "끝"}], "enemy": []})  # 11~15분이 빔
    _write(g, "turns-4", {"ally": [], "enemy": []})
    assert parallel.gaps(g, ws, 26) == [(660, 900)]


def test_gaps_allows_respawn_after_death(tmp_path):
    g = _game(tmp_path)
    ws = parallel.workers(g, "pro")
    _write(g, "turns-1", {"ally": [{"id": "a", "from": "1:30", "to": "5:00", "end": "사망"},
                                   {"id": "b", "from": "6:30", "to": "26:00", "end": "끝"}], "enemy": []})
    for k in (2, 3, 4):
        _write(g, f"turns-{k}", {"ally": [], "enemy": []})
    assert parallel.gaps(g, ws, 26) == []
