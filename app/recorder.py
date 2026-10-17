"""Continuous recording: one supervised ffmpeg process per camera.

ffmpeg copies the camera's video stream without re-encoding (minimal CPU)
into fragmented-MP4 HLS segments on the NAS. Audio is converted to AAC so
browsers can play it. A small indexer follows the playlist ffmpeg writes and
stores every finished segment in SQLite together with its real start time.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Camera, Config
from .db import Database
from .timeline import parse_live_playlist

log = logging.getLogger("nvr.recorder")

STORAGE_MARKER = ".nvr-storage"


def storage_ready(root: Path) -> bool:
    """True only if the NAS is mounted (marker exists) and writable.

    The marker prevents filling the server's local disk when the NFS mount
    is missing and /recordings is just an empty directory.
    """
    return (root / STORAGE_MARKER).is_file() and os.access(root, os.W_OK)


async def probe_codec(url: str, input_args: list[str], timeout: float = 20) -> str | None:
    args = ["ffprobe", "-v", "error", *input_args]
    if url.startswith("rtsp://"):
        args += ["-rtsp_transport", "tcp", "-timeout", "10000000"]
    args += ["-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", url]
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        codec = out.decode().strip().splitlines()
        return codec[0] if codec else None
    except (asyncio.TimeoutError, OSError):
        try:
            proc.kill()
        except Exception:
            pass
        return None


class CameraRecorder:
    def __init__(self, cfg: Config, cam: Camera, db: Database):
        self.cfg = cfg
        self.cam = cam
        self.db = db
        self.state = "starting"
        self.last_error = ""
        self.last_segment_at = 0.0
        self.restarts = 0
        self.codec: str | None = None
        self.session: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr = collections.deque(maxlen=20)
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    @property
    def source_url(self) -> str:
        if self.cam.record_url:
            return self.cam.record_url
        if self.cfg.record_via_go2rtc:
            return f"{self.cfg.go2rtc_rtsp}/{self.cam.id}"
        return self.cam.main_rtsp

    def status(self) -> dict:
        return {
            "state": self.state,
            "last_segment_at": self.last_segment_at,
            "last_error": self.last_error,
            "restarts": self.restarts,
            "codec": self.codec,
            "session": self.session,
        }

    def build_command(self, sess: str, sess_dir: Path) -> list[str]:
        root = self.cfg.storage_path
        url = self.source_url
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-y"]
        cmd += self.cam.record_input_args
        if url.startswith("rtsp://"):
            cmd += ["-rtsp_transport", "tcp", "-timeout", "10000000"]
        cmd += ["-i", url, "-map", "0:v:0", "-c:v", "copy"]
        if self.codec == "hevc":
            cmd += ["-tag:v", "hvc1"]  # required by Safari / iOS
        elif self.codec == "h264":
            cmd += ["-tag:v", "avc1"]
        if self.cam.audio:
            cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "32k", "-ac", "1", "-ar", "16000"]
        seg_pattern = str(root / self.cam.id / "%Y-%m-%d" / f"%H%M%S-{sess}.m4s")
        cmd += [
            "-f", "hls",
            "-hls_time", str(self.cfg.segment_seconds),
            "-hls_list_size", "30",
            "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_flags", "program_date_time+independent_segments+temp_file",
            "-strftime", "1", "-strftime_mkdir", "1",
            "-hls_segment_filename", seg_pattern,
            str(sess_dir / "index.m3u8"),
        ]
        return cmd

    # ------------------------------------------------------------------
    async def run(self):
        backoff = 2
        while not self._stop.is_set():
            if not storage_ready(self.cfg.storage_path):
                self.state = "storage_missing"
                self.last_error = f"Úložiště {self.cfg.storage_path} není připojeno (chybí {STORAGE_MARKER})"
                await self._sleep(10)
                continue
            started = time.time()
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep supervising whatever happens
                log.exception("%s: recorder crashed", self.cam.id)
                self.last_error = str(exc)
            if self._stop.is_set():
                break
            self.restarts += 1
            self.state = "error"
            backoff = 2 if time.time() - started > 120 else min(backoff * 2, 60)
            await self._sleep(backoff)
        self.state = "stopped"

    async def _sleep(self, seconds: float):
        try:
            await asyncio.wait_for(self._stop.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    async def _run_once(self):
        self.state = "connecting"
        codec = await probe_codec(self.source_url, self.cam.record_input_args)
        if codec:
            self.codec = codec
        elif not self.codec:
            self.last_error = "Kamera nedostupná (ffprobe nevrátil stream)"
            return

        now = datetime.now(timezone.utc)
        sess = now.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(2)
        sess_dir = self.cfg.storage_path / self.cam.id / "sessions" / sess
        sess_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.build_command(sess, sess_dir)
        log.info("%s: starting session %s (%s)", self.cam.id, sess, self.codec)
        self._stderr.clear()
        # TZ=UTC: segment file names must not repeat when DST ends
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE, env={**os.environ, "TZ": "UTC"})
        self.session = sess
        stderr_task = asyncio.create_task(self._read_stderr(self._proc))
        registered = False
        seen: collections.OrderedDict[str, None] = collections.OrderedDict()
        playlist = sess_dir / "index.m3u8"
        journal = sess_dir / "segments.csv"
        root = self.cfg.storage_path
        stall_timeout = max(45, self.cfg.segment_seconds * 8)
        last_progress = time.time()
        try:
            while self._proc.returncode is None and not self._stop.is_set():
                await self._sleep(1)
                if not playlist.exists():
                    if time.time() - last_progress > stall_timeout:
                        self.last_error = "Žádná data z kamery: " + " | ".join(self._stderr)
                        break
                    continue
                try:
                    init_uri, entries = parse_live_playlist(playlist.read_text())
                except (OSError, ValueError):
                    continue
                if not registered:
                    init_rel = os.path.relpath(sess_dir / (init_uri or "init.mp4"), root)
                    self.db.add_session(sess, self.cam.id, time.time(), init_rel, self.codec)
                    registered = True
                rows = []
                for e in entries:
                    if e.uri in seen:
                        continue
                    seen[e.uri] = None
                    path = Path(e.uri)
                    if not path.is_absolute():
                        path = sess_dir / path
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    rows.append((self.cam.id, sess, e.start, e.duration, os.path.relpath(path, root), size))
                while len(seen) > 200:
                    seen.popitem(last=False)
                if rows:
                    self.db.add_segments(rows)
                    with journal.open("a") as fh:
                        for r in rows:
                            fh.write(f"{r[2]:.3f},{r[3]:.3f},{r[4]},{r[5]}\n")
                    last_progress = time.time()
                    self.last_segment_at = last_progress
                    self.state = "recording"
                    self.last_error = ""
                    drift = last_progress - (rows[-1][2] + rows[-1][3])
                    if abs(drift) > 20:
                        # Stream timestamps drifted from the wall clock; a new
                        # session re-anchors the time index.
                        log.warning("%s: clock drift %.1fs, restarting session", self.cam.id, drift)
                        break
                elif time.time() - last_progress > stall_timeout:
                    self.last_error = "Záznam se zastavil, restartuji"
                    log.warning("%s: stalled, restarting", self.cam.id)
                    break
        finally:
            await self._terminate()
            stderr_task.cancel()
            self.db.end_session(sess, time.time())
            if self._stderr and not self.last_error:
                self.last_error = " | ".join(list(self._stderr)[-3:])

    async def _read_stderr(self, proc):
        assert proc.stderr
        async for raw in proc.stderr:
            line = raw.decode(errors="replace").strip()
            if line:
                self._stderr.append(line[:300])

    async def _terminate(self):
        proc = self._proc
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def stop(self):
        self._stop.set()
        await self._terminate()


class RecorderManager:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.recorders = {c.id: CameraRecorder(cfg, c, db) for c in cfg.cameras if c.enabled}
        self._tasks: list[asyncio.Task] = []

    def start(self):
        for rec in self.recorders.values():
            self._tasks.append(asyncio.create_task(rec.run(), name=f"rec-{rec.cam.id}"))

    async def stop(self):
        await asyncio.gather(*(r.stop() for r in self.recorders.values()), return_exceptions=True)
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
