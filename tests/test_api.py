import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Camera, Config
from app.main import S, create_app


@pytest.fixture
def client(tmp_path: Path):
    cfg = Config(storage_path=tmp_path / "rec", data_path=tmp_path / "data", cookie_secure=False,
                 cameras=[Camera(id="cam1", name="Kamera 1", host="127.0.0.1")])
    (tmp_path / "rec").mkdir()
    app = create_app(cfg, start_background=False)
    with TestClient(app) as c:
        auth.create_user(S.db, "jan", "velmi-tajne-heslo")
        now = time.time()
        S.db.add_session("s1", "cam1", now - 100, "cam1/sessions/s1/init.mp4", "hevc")
        S.db.add_segments([("cam1", "s1", now - 100 + i * 6, 6.0, f"cam1/d/{i}.m4s", 1000) for i in range(5)]
                          + [("cam1", "s1", now - 40 + i * 6, 6.0, f"cam1/d/b{i}.m4s", 1000) for i in range(3)])
        S.db.open_event("cam1", now - 90)
        S.db.close_event("cam1", now - 80)
        yield c


def login(c, pw="velmi-tajne-heslo", hdr=True):
    return c.post("/api/login", json={"username": "jan", "password": pw}, headers={"X-NVR": "1"} if hdr else {})


def test_requires_login(client):
    assert client.get("/api/config").status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 303


def test_csrf_header_required(client):
    assert login(client, hdr=False).status_code == 403


def test_login_wrong_password_and_rate_limit(client):
    for _ in range(6):
        assert login(client, pw="spatne-heslo-xx").status_code == 401
    assert login(client).status_code == 429


def test_coverage_and_playlist(client):
    assert login(client).status_code == 200
    now = time.time()
    cov = client.get(f"/api/coverage?start={now - 200}&end={now}").json()["cameras"]["cam1"]
    assert len(cov["intervals"]) == 2           # the gap between the two runs is visible
    assert len(cov["events"]) == 1
    idx = client.get(f"/api/playback/cam1/index?start={now - 200}&end={now}").json()
    assert idx["codec"] == "hevc" and len(idx["segments"]) == 8
    pl = client.get(f"/api/playback/cam1/playlist.m3u8?start={now - 200}&end={now}").text
    assert pl.count("#EXTINF") == 8 and "#EXT-X-DISCONTINUITY" in pl
    tc = client.get(f"/api/playback/cam1/playlist.m3u8?start={now - 200}&end={now}&tc=1").text
    assert "/api/tc/" in tc and "EXT-X-MAP" not in tc


def test_live_proxy_rejects_unknown_stream(client):
    login(client)
    assert client.get("/live/api/frame.jpeg?src=../../api/streams").status_code == 404


def test_prefs_roundtrip(client):
    login(client)
    r = client.put("/api/me/prefs", json={"layout": 4, "hidden": ["cam1"]}, headers={"X-NVR": "1"})
    assert r.status_code == 200
    assert client.get("/api/me").json()["prefs"]["layout"] == 4
