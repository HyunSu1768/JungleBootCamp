"""판 끝난 뒤 복기: 잠금, 내 복기, 복기 노트, 목표 이어가기"""

import datetime as dt
import json
import time

from server import db, debrief, mine
from server.jobs import VODS


def deliver(client, headers, tmp_path, gid, duration=1700, deaths=(380,), ended_ago=0):
    rec = tmp_path / gid
    rec.mkdir()
    (rec / "recording.mkv").write_bytes(b"x")
    started = dt.datetime.now() - dt.timedelta(seconds=duration + ended_ago)
    meta = {"id": gid, "started_at": started.isoformat(timespec="seconds"), "duration": duration, "offset": 30, "result": "패",
            "me": {"riot_id": "나#KR1", "champion": "자르반 4세", "position": "JUNGLE"},
            "events": [{"EventID": i, "EventName": "ChampionKill", "EventTime": t, "KillerName": "적#KR1", "VictimName": "나#KR1", "Assisters": []}
                       for i, t in enumerate(deaths)],
            "snapshots": [{"t": 600, "players": [{"champion": "자르반 4세", "riot_id": "나#KR1", "team": "ORDER", "scores": {}},
                                                 {"champion": "아트록스", "riot_id": "적#KR1", "team": "CHAOS", "scores": {}}]}]}
    (rec / "live.json").write_text(json.dumps(meta, ensure_ascii=False))
    return client.post("/api/agent/recordings", headers=headers, json={"path": str(rec / "recording.mkv"), "meta": meta}).json()


def test_lock_status_and_blocked(client, agent_headers, tmp_path):
    r = deliver(client, agent_headers, tmp_path, "g-lock")
    assert 590 < r["lock_until"] - time.time() <= 600
    assert client.post("/api/agent/status", headers=agent_headers, json={"state": "waiting"}).json()["lock_until"] == r["lock_until"]
    client.post("/api/agent/blocked", headers=agent_headers, json={"phase": "Matchmaking"})
    act = client.get("/api/debrief/active").json()["active"]
    assert act["game_id"] == "g-lock" and act["locked"] and act["blocked"] == 1
    d = client.get("/api/debrief/g-lock").json()
    assert d["deaths"] == [{"t": "6:20", "sec": 380, "killer": "아트록스", "assisters": 0}]


def test_late_delivery_locks_only_the_rest(client, agent_headers, tmp_path):
    deliver(client, agent_headers, tmp_path, "g-late", ended_ago=400)
    assert 190 < debrief.get_row("local", "g-late")["lock_until"] - time.time() <= 200
    deliver(client, agent_headers, tmp_path, "g-old", ended_ago=1200)
    assert debrief.get_row("local", "g-old")["lock_until"] is None


def test_short_game_not_locked(client, agent_headers, tmp_path):
    deliver(client, agent_headers, tmp_path, "g-remake", duration=200)
    assert debrief.get_row("local", "g-remake") is None


def test_lessons_accumulate_across_games():
    db.x("INSERT OR IGNORE INTO my_games (id, user_id, dir, created) VALUES ('L1', 'u-lessons', 'x', ?), ('L2', 'u-lessons', 'y', ?)", (db.now(), db.now()))
    first = {"lessons": [{"lesson_id": None, "kind": "mistake", "category": "오브젝트", "title": "귀환 없이 용", "when": "w", "then": "t", "outcome": "first"}]}
    assert debrief.ingest("u-lessons", "L1", first) == 1
    lid = debrief.lessons("u-lessons")[0]["id"]
    again = {"lessons": [{"lesson_id": lid, "kind": "mistake", "title": "귀환 없이 용", "outcome": "again"},
                         {"lesson_id": None, "kind": "strength", "title": "용 주고 반대편", "outcome": "kept"}]}
    debrief.ingest("u-lessons", "L2", again)
    debrief.ingest("u-lessons", "L2", again)  # 같은 판을 다시 분석해도 두 번 세지 않는다
    ls = {le["title"]: le for le in debrief.lessons("u-lessons")}
    assert ls["귀환 없이 용"]["games"] == 2 and ls["귀환 없이 용"]["again"] == 2
    assert ls["용 주고 반대편"]["kind"] == "strength"
    assert debrief.lessons("u-lessons")[0]["kind"] == "mistake"  # 고칠 것이 먼저


def test_goal_carries_until_kept_twice(client, agent_headers, tmp_path):
    client.post("/api/goals", json={"text": "바텀이 밀리면 → 위쪽 캠프", "rule_id": None})
    for k in range(3):
        deliver(client, agent_headers, tmp_path, f"g-goal{k}")
        g = client.get("/api/goals").json()
        assert g["active"]["text"] == "바텀이 밀리면 → 위쪽 캠프"  # 판이 끝나도 같은 목표가 이어진다
        assert g["active"]["source"] == "carry"
        linked = db.q("SELECT id FROM goals WHERE game_id = ?", (f"g-goal{k}",))[0]
        # 다음 목표 후보가 있는 총평
        gdir = VODS / "mine" / "local" / f"g-goal{k}" / "game1"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "analysis.json").write_text(json.dumps({"version": 2, "next_goal": {"when": "용 1분 전", "then": "바텀 확인"}}, ensure_ascii=False))
        client.put(f"/api/goals/{linked['id']}", json={"followed": ["no", "yes", "yes"][k]})
    g = client.get("/api/goals").json()
    assert g["active"]["text"] == "용 1분 전 → 바텀 확인" and g["active"]["source"] == "coach"  # 2판 연속 지켜서 다음 목표로
    assert mine.goal_progress("local", "바텀이 밀리면 → 위쪽 캠프")["mastered"]


def test_coach_context_has_all_sources(client, agent_headers, tmp_path):
    deliver(client, agent_headers, tmp_path, "g-ctx")
    client.put("/api/debrief/g-ctx/self", json={"deaths": [{"t": "6:20", "reason": "무리한 교전"}], "moment": "6분"})
    gdir = VODS / "mine" / "local" / "g-ctx" / "game1"
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "analysis.json").write_text(json.dumps({"version": 2, "champion": "자르반 4세", "enemy_jungler": "아트록스"}, ensure_ascii=False))
    text = debrief.coach_context("local", "g-ctx", gdir).read_text()
    for part in ("플레이어가 먼저 한 복기", "데스 6:20: 무리한 교전", "지금 목표", "복기 노트", "가까운 프로 판", "원칙"):
        assert part in text
