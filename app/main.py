"""FastAPI application: REST API, live proxy and the web UI."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import auth
from .config import Config, load_config
from .db import Database
from .live import proxy_websocket, stream_names, sync_go2rtc
from .media import MediaError, Transcoder, export_mp4
from .onvif import OnvifEvents
from .recorder import RecorderManager
from .retention import Janitor, storage_stats
from .timeline import build_m3u8, clip_events, merge_intervals, select_playback

log = logging.getLogger("nvr")
WEB_DIR = Path(os.environ.get("NVR_WEB_DIR", Path(__file__).resolve().parent.parent / "web"))
MAX_RANGE = 26 * 3600


class State:
    cfg: Config
    db: Database
    recorders: RecorderManager
    janitor: Janitor
    transcoder: Transcoder
    onvif: dict[str, OnvifEvents]
    tasks: list[asyncio.Task]


S = State()


def create_app(cfg: Config | None = None, start_background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        S.cfg = cfg or load_config()
        S.db = Database(S.cfg.data_path / "nvr.db")
        cache = S.cfg.data_path / "cache"
        S.transcoder = Transcoder(S.cfg, cache)
        S.janitor = Janitor(S.cfg, S.db, cache)
        S.recorders = RecorderManager(S.cfg, S.db)
        S.onvif = {}
        S.tasks = []
        # Sessions left open by a crash
        S.db.execute("UPDATE rec_sessions SET ended=? WHERE ended IS NULL", (time.time(),))
        S.db.execute("UPDATE events SET end=start WHERE end IS NULL")
        if start_background:
            # go2rtc may still be starting; recorders retry until it is ready
            S.tasks.append(asyncio.create_task(sync_go2rtc(S.cfg)))
            S.recorders.start()
            S.tasks.append(asyncio.create_task(S.janitor.run()))
            for cam in S.cfg.cameras:
                if cam.enabled and cam.onvif:
                    listener = OnvifEvents(cam, _motion_cb(cam.id))
                    S.onvif[cam.id] = listener
                    S.tasks.append(asyncio.create_task(listener.run()))
        yield
        for t in S.tasks:
            t.cancel()
        await asyncio.gather(*S.tasks, return_exceptions=True)
        await S.recorders.stop()
        S.db.close()

    app = FastAPI(title="FarNVR", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    _routes(app)
    return app


def _motion_cb(cam_id: str):
    def cb(active: bool):
        now = time.time()
        if active:
            S.db.open_event(cam_id, now)
        else:
            S.db.close_event(cam_id, now)
    return cb


# --------------------------------------------------------------------------
# dependencies

def current_user(request: Request) -> dict:
    user = auth.session_user(S.db, request.cookies.get(auth.COOKIE), S.cfg.session_days)
    if not user:
        raise HTTPException(401, "login_required")
    return user


def csrf(request: Request):
    # A custom header cannot be sent cross-site without a CORS preflight,
    # which we never allow. Combined with SameSite=Strict cookies.
    if request.headers.get("x-nvr") != "1":
        raise HTTPException(403, "csrf")


def camera_or_404(cam_id: str):
    cam = S.cfg.camera(cam_id)
    if not cam or not cam.enabled:
        raise HTTPException(404, "unknown_camera")
    return cam


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    otp: str | None = Field(default=None, max_length=12)


class PasswordBody(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(min_length=10, max_length=256)


def _check_range(start: float, end: float, limit: float = MAX_RANGE):
    if end <= start or end - start > limit:
        raise HTTPException(400, "invalid_range")


def _routes(app: FastAPI):
    login_ip_limit = auth.RateLimiter(20, 900)
    login_user_limit = auth.RateLimiter(6, 600)

    # ---------------------------------------------------------------- auth
    @app.post("/api/login", dependencies=[Depends(csrf)])
    async def login(body: LoginBody, request: Request):
        ip = client_ip(request)
        ukey = body.username.strip().lower()
        if login_ip_limit.blocked(ip) or login_user_limit.blocked(ukey):
            raise HTTPException(429, "too_many_attempts")
        user_id, err = await asyncio.to_thread(auth.verify_login, S.db, body.username, body.password, body.otp)
        if not user_id:
            if err != "otp_required":
                login_ip_limit.hit(ip)
                login_user_limit.hit(ukey)
            raise HTTPException(401, err)
        login_user_limit.reset(ukey)
        token = auth.create_session(S.db, user_id, S.cfg.session_days, ip, request.headers.get("user-agent", ""))
        resp = JSONResponse({"ok": True})
        resp.set_cookie(auth.COOKIE, token, max_age=S.cfg.session_days * 86400, httponly=True,
                        secure=S.cfg.cookie_secure, samesite="strict", path="/")
        return resp

    @app.post("/api/logout", dependencies=[Depends(csrf)])
    async def logout(request: Request):
        auth.delete_session(S.db, request.cookies.get(auth.COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    @app.get("/api/me")
    async def me(user=Depends(current_user)):
        return {**user, "prefs": S.db.user_prefs(user["id"])}

    @app.put("/api/me/prefs", dependencies=[Depends(csrf)])
    async def put_prefs(request: Request, user=Depends(current_user)):
        body = await request.body()
        if len(body) > 16384:
            raise HTTPException(413)
        prefs = await request.json()
        if not isinstance(prefs, dict):
            raise HTTPException(400)
        S.db.set_user_prefs(user["id"], prefs)
        return {"ok": True}

    @app.post("/api/me/password", dependencies=[Depends(csrf)])
    async def change_password(body: PasswordBody, request: Request, user=Depends(current_user)):
        uid, err = await asyncio.to_thread(auth.verify_login, S.db, user["username"], body.current, None)
        if not uid and err != "otp_required":
            raise HTTPException(400, "invalid_password")
        auth.set_password(S.db, user["id"], body.new)
        token = auth.create_session(S.db, user["id"], S.cfg.session_days, client_ip(request),
                                    request.headers.get("user-agent", ""))
        resp = JSONResponse({"ok": True})
        resp.set_cookie(auth.COOKIE, token, max_age=S.cfg.session_days * 86400, httponly=True,
                        secure=S.cfg.cookie_secure, samesite="strict", path="/")
        return resp

    # ------------------------------------------------------------- cameras
    @app.get("/api/config")
    async def get_config(user=Depends(current_user)):
        return {
            "site_name": S.cfg.site_name,
            "segment_seconds": S.cfg.segment_seconds,
            "retention_days": S.cfg.retention_days,
            "webrtc": S.cfg.webrtc,
            "cameras": [{"id": c.id, "name": c.name, "mode": c.mode, "audio": c.audio}
                        for c in S.cfg.cameras if c.enabled],
        }

    @app.get("/api/status")
    async def status(user=Depends(current_user)):
        cams = {}
        for cam_id, rec in S.recorders.recorders.items():
            st = rec.status()
            ev = S.onvif.get(cam_id)
            st["onvif"] = {"state": ev.state, "last_error": ev.last_error,
                           "last_event_at": ev.last_event_at} if ev else None
            row = S.db.one("SELECT 1 FROM events WHERE cam=? AND end IS NULL", (cam_id,))
            st["motion"] = bool(row)
            cams[cam_id] = st
        stats = await asyncio.to_thread(storage_stats, S.cfg, S.db)
        return {"time": time.time(), "cameras": cams, "storage": stats}

    @app.get("/api/coverage")
    async def coverage(start: float, end: float, cams: str | None = None, user=Depends(current_user)):
        _check_range(start, end, 32 * 86400)
        ids = cams.split(",") if cams else [c.id for c in S.cfg.cameras if c.enabled]
        now = time.time()
        out = {}
        for cam_id in ids:
            camera_or_404(cam_id)
            rows = S.db.query("SELECT start, duration FROM segments WHERE cam=? AND start>=? AND start<? "
                              "ORDER BY start", (cam_id, start - 120, end))
            out[cam_id] = {
                "intervals": merge_intervals([(r["start"], r["duration"]) for r in rows], start, end),
                "events": clip_events(S.db.events_between(cam_id, start, end), start, end, now),
            }
        return {"start": start, "end": end, "now": now, "cameras": out}

    @app.get("/api/cameras/{cam_id}/days")
    async def days(cam_id: str, year: int, month: int, tz: str = "Europe/Prague", user=Depends(current_user)):
        camera_or_404(cam_id)
        try:
            zone = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        if not (1 <= month <= 12 and 2000 < year < 2200):
            raise HTTPException(400)
        result = []
        day = datetime(year, month, 1, tzinfo=zone)
        while day.month == month:
            nxt = (day + timedelta(days=1, hours=2)).replace(hour=0, minute=0, second=0)
            row = S.db.one("SELECT 1 FROM segments WHERE cam=? AND start>=? AND start<? LIMIT 1",
                           (cam_id, day.timestamp(), nxt.timestamp()))
            if row:
                result.append(day.day)
            day = nxt
        return {"days": result}

    # ------------------------------------------------------------ playback
    def _playback_items(cam_id: str, start: float, end: float):
        _check_range(start, end)
        rows = S.db.segments_between(cam_id, start, end)
        return select_playback(rows, start, end)

    @app.get("/api/playback/{cam_id}/index")
    async def playback_index(cam_id: str, start: float, end: float, user=Depends(current_user)):
        camera_or_404(cam_id)
        items = _playback_items(cam_id, start, end)
        sess_ids = sorted({i["sess"] for i in items})
        codecs = {}
        for sid in sess_ids:
            row = S.db.one("SELECT codec FROM rec_sessions WHERE id=?", (sid,))
            codecs[sid] = row["codec"] if row else None
        codec = "hevc" if "hevc" in codecs.values() else (next(iter(codecs.values()), None) or "h264")
        return {"segments": [[i["start"], i["dur"], i["offset"]] for i in items], "codec": codec}

    @app.get("/api/playback/{cam_id}/playlist.m3u8")
    async def playlist(cam_id: str, start: float, end: float, tc: int = 0, user=Depends(current_user)):
        camera_or_404(cam_id)
        items = _playback_items(cam_id, start, end)
        if not items:
            raise HTTPException(404, "no_recording")
        if tc:
            text = build_m3u8(items, lambda i: f"/api/tc/{i['id']}.ts?o={i['offset']}", None, transcoded=True)
        else:
            text = build_m3u8(items, lambda i: f"/api/seg/{i['id']}.m4s", lambda s: f"/api/init/{s}.mp4")
        return Response(text, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-store"})

    def _seg_file(seg_id: int) -> tuple[Path, dict]:
        row = S.db.one("SELECT g.path, g.sess, s.init_path FROM segments g JOIN rec_sessions s ON s.id=g.sess "
                       "WHERE g.id=?", (seg_id,))
        if not row:
            raise HTTPException(404)
        return S.cfg.storage_path / row["path"], dict(row)

    @app.get("/api/seg/{seg_id}.m4s")
    async def segment(seg_id: int, user=Depends(current_user)):
        path, _ = _seg_file(seg_id)
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/iso.segment", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/init/{sess}.mp4")
    async def init_segment(sess: str, user=Depends(current_user)):
        row = S.db.one("SELECT init_path FROM rec_sessions WHERE id=?", (sess,))
        if not row:
            raise HTTPException(404)
        path = S.cfg.storage_path / row["init_path"]
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/tc/{seg_id}.ts")
    async def transcoded(seg_id: int, o: float = 0.0, user=Depends(current_user)):
        path, row = _seg_file(seg_id)
        init = S.cfg.storage_path / row["init_path"]
        if not path.exists() or not init.exists():
            raise HTTPException(404)
        try:
            out = await S.transcoder.segment_ts(init, path, seg_id, max(0.0, o))
        except MediaError as exc:
            log.warning("transcode %s failed: %s", seg_id, exc)
            raise HTTPException(500, "transcode_failed")
        return FileResponse(out, media_type="video/mp2t", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/export")
    async def export(cam: str, start: float, end: float, h264: int = 0, user=Depends(current_user)):
        camera_or_404(cam)
        _check_range(start, end, S.cfg.export_max_seconds)
        try:
            out, tmp = await export_mp4(S.cfg, S.db, cam, start, end, bool(h264))
        except MediaError as exc:
            raise HTTPException(400, str(exc))
        name = f"{cam}_{datetime.fromtimestamp(start).strftime('%Y%m%d-%H%M%S')}.mp4"
        return FileResponse(out, media_type="video/mp4", filename=name,
                            background=BackgroundTask(shutil.rmtree, tmp, True))

    # ---------------------------------------------------------------- live
    allowed_streams = None

    def _stream_ok(src: str) -> bool:
        nonlocal allowed_streams
        if allowed_streams is None:
            allowed_streams = stream_names(S.cfg)
        return src in allowed_streams

    @app.websocket("/live/api/ws")
    async def live_ws(ws: WebSocket, src: str = Query(...)):
        user = auth.session_user(S.db, ws.cookies.get(auth.COOKIE), S.cfg.session_days)
        origin = ws.headers.get("origin")
        host = ws.headers.get("host")
        if not user or not _stream_ok(src) or (origin and urlsplit(origin).netloc != host):
            await ws.close(code=4401)
            return
        await ws.accept()
        base = S.cfg.go2rtc_api.replace("http://", "ws://").replace("https://", "wss://")
        await proxy_websocket(ws, f"{base}/api/ws?{urlencode({'src': src})}")

    @app.get("/live/api/hls/{path:path}")
    async def live_hls(path: str, request: Request, user=Depends(current_user)):
        return await _proxy_get(f"/api/hls/{path}", request.url.query)

    @app.get("/live/api/frame.jpeg")
    async def live_frame(src: str, user=Depends(current_user)):
        if not _stream_ok(src):
            raise HTTPException(404)
        return await _proxy_get("/api/frame.jpeg", urlencode({"src": src}))

    async def _proxy_get(path: str, query: str):
        if ".." in path:
            raise HTTPException(400)
        url = f"{S.cfg.go2rtc_api}{path}" + (f"?{query}" if query else "")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(url)
        except httpx.HTTPError:
            raise HTTPException(502, "live_unavailable")
        return Response(r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/octet-stream"),
                        headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ ui
    @app.get("/healthz")
    async def healthz():
        return PlainTextResponse("ok")

    @app.get("/")
    async def index(request: Request):
        if not auth.session_user(S.db, request.cookies.get(auth.COOKIE), S.cfg.session_days):
            return RedirectResponse("/login.html", status_code=303)
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob: data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; worker-src 'self' blob:; "
            "connect-src 'self' ws: wss:; frame-ancestors 'none'")
        return resp

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")

