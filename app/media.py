"""ffmpeg helpers for playback fallback (H.264 transcode) and MP4 export."""
from __future__ import annotations

import asyncio
import itertools
import shutil
import tempfile
from pathlib import Path

from .config import Config
from .db import Database


class MediaError(Exception):
    pass


async def _run_ffmpeg(args: list[str], stdin_files: list[Path] | None = None, timeout: float = 600) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin" if stdin_files is None else "-y", *args,
        stdin=asyncio.subprocess.PIPE if stdin_files is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def feed():
        try:
            for f in stdin_files or []:
                with f.open("rb") as fh:
                    while chunk := fh.read(1 << 20):
                        proc.stdin.write(chunk)
                        await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if proc.stdin:
                proc.stdin.close()

    feeder = asyncio.create_task(feed()) if stdin_files is not None else None
    try:
        out, err = await asyncio.wait_for(proc.communicate() if feeder is None else _collect(proc), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaError("ffmpeg timeout")
    finally:
        if feeder:
            await asyncio.gather(feeder, return_exceptions=True)
    if proc.returncode != 0:
        raise MediaError(err.decode(errors="replace")[-500:])
    return out


async def _collect(proc):
    out, err = await asyncio.gather(proc.stdout.read(), proc.stderr.read())
    await proc.wait()
    return out, err


class Transcoder:
    """H.265 -> H.264 per-segment transcode for browsers without HEVC support."""

    def __init__(self, cfg: Config, cache_dir: Path):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._sem = asyncio.Semaphore(cfg.transcode_workers)
        self._inflight: dict[str, asyncio.Future] = {}

    async def segment_ts(self, init: Path, seg: Path, seg_id: int, offset: float) -> Path:
        out = self.cache_dir / f"{seg_id}-{int(offset * 1000)}.ts"
        if out.exists():
            return out
        key = out.name
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            async with self._sem:
                h = self.cfg.transcode_height
                data = await _run_ffmpeg([
                    "-f", "mp4", "-i", "pipe:0",
                    "-map", "0:v:0", "-map", "0:a:0?",
                    "-vf", f"scale=-2:'min({h},ih)'",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "48k",
                    "-output_ts_offset", f"{offset:.3f}", "-muxdelay", "0", "-muxpreload", "0",
                    "-f", "mpegts", "pipe:1",
                ], stdin_files=[init, seg], timeout=120)
            tmp = out.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(out)
            fut.set_result(out)
            return out
        except Exception as exc:
            fut.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)
            if not fut.done():
                fut.cancel()
            elif fut.exception() is not None:
                fut.exception()  # mark retrieved


_export_lock = asyncio.Semaphore(1)


async def export_mp4(cfg: Config, db: Database, cam: str, start: float, end: float, h264: bool) -> tuple[Path, Path]:
    """Build an MP4 for [start, end]. Returns (file, tempdir_to_remove)."""
    rows = [r for r in db.segments_between(cam, start, end) if r["start"] + r["duration"] > start]
    if not rows:
        raise MediaError("V zadaném čase není žádný záznam")
    root = cfg.storage_path
    tmp = Path(tempfile.mkdtemp(prefix="nvr-export-"))
    try:
        async with _export_lock:
            parts = []
            for i, (sess, group) in enumerate(itertools.groupby(rows, key=lambda r: r["sess"])):
                srow = db.one("SELECT init_path FROM rec_sessions WHERE id=?", (sess,))
                if not srow:
                    continue
                files = [root / srow["init_path"]] + [root / r["path"] for r in group]
                files = [f for f in files if f.exists()]
                if len(files) < 2:
                    continue
                part = tmp / f"part{i:04d}.mp4"
                await _run_ffmpeg(["-f", "mp4", "-i", "pipe:0", "-map", "0", "-c", "copy", str(part)],
                                  stdin_files=files, timeout=1800)
                parts.append(part)
            if not parts:
                raise MediaError("Soubory záznamu nebyly nalezeny")
            out = tmp / "export.mp4"
            lst = tmp / "list.txt"
            lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
            codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac"] \
                if h264 else ["-c", "copy"]
            await _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0", *codec,
                               "-movflags", "+faststart", str(out)], timeout=3600)
            return out, tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
