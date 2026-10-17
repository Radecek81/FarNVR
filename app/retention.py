"""Housekeeping: retention by age and free space, motion-only pruning, cleanup."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

from .config import Config
from .db import Database
from .timeline import keep_for_motion

log = logging.getLogger("nvr.retention")


def disk_usage_percent(path: Path) -> float:
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return 0.0
    return 100.0 * u.used / u.total if u.total else 0.0


class Janitor:
    def __init__(self, cfg: Config, db: Database, cache_dir: Path):
        self.cfg = cfg
        self.db = db
        self.cache_dir = cache_dir
        self.last_run = 0.0

    def _delete_rows(self, rows) -> int:
        root = self.cfg.storage_path
        ids = []
        for r in rows:
            try:
                (root / r["path"]).unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("cannot delete %s: %s", r["path"], exc)
                continue
            ids.append((r["id"],))
        if ids:
            self.db.executemany("DELETE FROM segments WHERE id=?", ids)
        return len(ids)

    def prune_age(self, now: float) -> int:
        cutoff = now - self.cfg.retention_days * 86400
        total = 0
        while True:
            rows = self.db.query("SELECT id, path FROM segments WHERE start<? ORDER BY start LIMIT 2000", (cutoff,))
            if not rows:
                break
            total += self._delete_rows(rows)
        self.db.execute("DELETE FROM events WHERE start<?", (cutoff,))
        return total

    def prune_space(self) -> int:
        total = 0
        root = self.cfg.storage_path
        for _ in range(200):  # safety bound per run
            if disk_usage_percent(root) <= self.cfg.max_usage_percent:
                break
            rows = self.db.query("SELECT id, path FROM segments ORDER BY start LIMIT 300")
            if not rows:
                break
            total += self._delete_rows(rows)
        if total:
            log.warning("disk above %.0f%%, deleted %d oldest segments", self.cfg.max_usage_percent, total)
        return total

    def prune_motion(self, now: float) -> int:
        """For cameras in motion mode keep only segments near motion events."""
        cfg = self.cfg
        # Close events whose "motion end" message never arrived.
        self.db.execute("UPDATE events SET end=start+? WHERE end IS NULL AND start<?",
                        (cfg.max_event_seconds, now - cfg.max_event_seconds))
        deleted = 0
        settle = now - cfg.post_seconds - 2 * cfg.segment_seconds
        for cam in cfg.cameras:
            if cam.mode != "motion":
                continue
            rows = self.db.query(
                "SELECT id, start, duration, path FROM segments WHERE cam=? AND keep IS NULL AND start+duration<? "
                "ORDER BY start LIMIT 5000", (cam.id, settle))
            if not rows:
                continue
            events = self.db.events_between(cam.id, rows[0]["start"] - cfg.post_seconds,
                                            rows[-1]["start"] + rows[-1]["duration"] + cfg.pre_seconds)
            keep, drop = [], []
            for r in rows:
                if keep_for_motion(r["start"], r["duration"], events, cfg.pre_seconds, cfg.post_seconds, now):
                    keep.append((r["id"],))
                else:
                    drop.append(r)
            if keep:
                self.db.executemany("UPDATE segments SET keep=1 WHERE id=?", keep)
            deleted += self._delete_rows(drop)
        return deleted

    def cleanup(self, now: float):
        root = self.cfg.storage_path
        # Ended sessions without any remaining segments
        rows = self.db.query(
            "SELECT s.id, s.cam FROM rec_sessions s WHERE s.ended IS NOT NULL AND s.ended<? "
            "AND NOT EXISTS (SELECT 1 FROM segments g WHERE g.sess=s.id)", (now - 3600,))
        for r in rows:
            shutil.rmtree(root / r["cam"] / "sessions" / r["id"], ignore_errors=True)
            self.db.execute("DELETE FROM rec_sessions WHERE id=?", (r["id"],))
        # Empty day directories
        for cam in self.cfg.cameras:
            cam_dir = root / cam.id
            if not cam_dir.is_dir():
                continue
            for d in cam_dir.iterdir():
                if d.is_dir() and d.name != "sessions":
                    try:
                        d.rmdir()  # only succeeds when empty
                    except OSError:
                        pass
        self.db.execute("DELETE FROM login_sessions WHERE expires<?", (now,))
        # Transcode cache older than 2 hours
        if self.cache_dir.is_dir():
            for f in self.cache_dir.iterdir():
                try:
                    if f.stat().st_mtime < now - 7200:
                        f.unlink()
                except OSError:
                    pass

    def run_once(self):
        now = time.time()
        from .recorder import storage_ready
        if storage_ready(self.cfg.storage_path):
            self.prune_motion(now)
            self.prune_age(now)
            self.prune_space()
            self.cleanup(now)
        self.last_run = now

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                log.exception("janitor failed")
            await asyncio.sleep(60)


def storage_stats(cfg: Config, db: Database) -> dict:
    root = cfg.storage_path
    try:
        u = shutil.disk_usage(root)
        total, used, free = u.total, u.used, u.free
    except OSError:
        total = used = free = 0
    now = time.time()
    rows = db.query("SELECT cam, SUM(size) AS bytes, MIN(start) AS oldest FROM segments GROUP BY cam")
    per_cam = {r["cam"]: {"bytes": r["bytes"] or 0, "oldest": r["oldest"]} for r in rows}
    day = db.query("SELECT cam, SUM(size) AS bytes FROM segments WHERE start>? GROUP BY cam", (now - 86400,))
    for r in day:
        per_cam.setdefault(r["cam"], {"bytes": 0, "oldest": None})["bytes_24h"] = r["bytes"] or 0
    # Extrapolate when the system has been recording for less than a day
    daily = 0.0
    for v in per_cam.values():
        observed = min(86400.0, now - v["oldest"]) if v.get("oldest") else 0
        if observed > 600:
            daily += v.get("bytes_24h", 0) * 86400.0 / observed
    daily = int(daily)
    stored = sum(v["bytes"] for v in per_cam.values())
    usable = total * cfg.max_usage_percent / 100 - (used - stored)
    return {
        "total": total, "used": used, "free": free,
        "usage_percent": round(100 * used / total, 1) if total else 0,
        "daily_bytes": daily,
        "capacity_days": round(usable / daily, 1) if daily else None,
        "retention_days": cfg.retention_days,
        "cameras": per_cam,
        "mounted": os.path.isfile(root / ".nvr-storage"),
    }
