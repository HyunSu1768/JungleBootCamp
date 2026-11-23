"""녹화 에이전트: 복기 시간에 큐 막기 (가짜 롤 클라이언트)"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import recorder


@pytest.fixture()
def lcu(tmp_path):
    state = {"phase": "Lobby", "calls": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body=b""):
            self.send_response(200 if body else 204)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            assert self.headers["Authorization"].startswith("Basic ")
            self._send(json.dumps(state["phase"]).encode())

        def do_DELETE(self):
            state["calls"].append(("DELETE", self.path))
            state["phase"] = "Lobby"
            self._send()

        def do_POST(self):
            state["calls"].append(("POST", self.path))
            self._send()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    lock = tmp_path / "lockfile"
    lock.write_text(f"LeagueClient:1:{srv.server_port}:pw:http")
    yield recorder.LeagueClient(str(lock)), state
    srv.shutdown()


def test_cancels_matchmaking(lcu):
    c, st = lcu
    st["phase"] = "Matchmaking"
    assert c.stop_queue() == "Matchmaking"
    assert st["calls"] == [("DELETE", "/lol-lobby/v2/lobby/matchmaking/search")]


def test_declines_ready_check(lcu):
    c, st = lcu
    st["phase"] = "ReadyCheck"
    assert c.stop_queue() == "ReadyCheck"
    assert ("POST", "/lol-matchmaking/v1/ready-check/decline") in st["calls"]


@pytest.mark.parametrize("phase", ["Lobby", "ChampSelect", "InProgress", "EndOfGame"])
def test_leaves_other_phases(lcu, phase):
    c, st = lcu
    st["phase"] = phase
    assert c.stop_queue() is None and st["calls"] == []
    assert c.last_phase == phase


def test_no_client():
    c = recorder.LeagueClient("/nonexistent/lockfile")
    assert c.phase() is None and c.stop_queue() is None


def test_deaths_counted_by_riot_id(tmp_path):
    class A:
        screen, audio, fps, height, bitrate = "0", None, 30, 1080, "6M"
    r = recorder.Recording(tmp_path, A())
    r.meta["me"] = {"riot_id": "나#KR1"}
    r.events = {1: {"EventName": "ChampionKill", "VictimName": "나"}, 2: {"EventName": "ChampionKill", "VictimName": "남"},
                3: {"EventName": "ChampionKill", "VictimName": "나#KR1"}}
    assert r.deaths() == 2
