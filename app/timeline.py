"""Pure helpers: m3u8 parsing, coverage merging and VOD playlist building."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

_TZ_BASIC = re.compile(r"([+-]\d\d)(\d\d)$")

# Two segments closer than this are treated as continuous recording.
GAP_TOLERANCE = 1.0


@dataclass
class LiveEntry:
    start: float
    duration: float
    uri: str


def parse_live_playlist(text: str) -> tuple[str | None, list[LiveEntry]]:
    """Parse the playlist written by ffmpeg's HLS muxer.

    Returns (init_uri, entries). Every entry must carry PROGRAM-DATE-TIME,
    which we request with -hls_flags program_date_time.
    """
    init_uri = None
    entries: list[LiveEntry] = []
    duration = None
    pdt = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            for part in line[len("#EXT-X-MAP:"):].split(","):
                if part.startswith("URI="):
                    init_uri = part[4:].strip('"')
        elif line.startswith("#EXTINF:"):
            duration = float(line[8:].split(",")[0])
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            # ffmpeg writes "+0000"; normalise to "+00:00" for every Python 3.x
            pdt = datetime.fromisoformat(_TZ_BASIC.sub(r"\1:\2", line.split(":", 1)[1].strip())).timestamp()
        elif not line.startswith("#"):
            if duration is not None and pdt is not None:
                entries.append(LiveEntry(pdt, duration, line))
            duration = None
            pdt = None
    return init_uri, entries


def merge_intervals(rows, start: float, end: float, tolerance: float = GAP_TOLERANCE) -> list[list[float]]:
    """rows: iterable of (start, duration) sorted by start. Clipped to [start, end]."""
    out: list[list[float]] = []
    for s, d in rows:
        e = s + d
        if e <= start or s >= end:
            continue
        s, e = max(s, start), min(e, end)
        if out and s - out[-1][1] <= tolerance:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [[round(a, 3), round(b, 3)] for a, b in out]


def clip_events(rows, start: float, end: float, now: float) -> list[list[float]]:
    out = []
    for r in rows:
        s = max(r["start"], start)
        e = min(r["end"] if r["end"] is not None else now, end)
        if e > s:
            out.append([round(s, 3), round(e, 3)])
    return out


def select_playback(rows, start: float, end: float) -> list[dict]:
    """Choose segments overlapping [start, end] and assign media offsets.

    Each item: id, sess, start, dur, offset, disc (discontinuity before it).
    The same list drives both the m3u8 and the client's time mapping.
    """
    items: list[dict] = []
    offset = 0.0
    prev = None
    for r in rows:
        s, d = r["start"], r["duration"]
        if s + d <= start or s >= end:
            continue
        disc = prev is not None and (r["sess"] != prev["sess"] or abs(s - (prev["start"] + prev["duration"])) > GAP_TOLERANCE)
        items.append({"id": r["id"], "sess": r["sess"], "start": round(s, 3), "dur": round(d, 3),
                      "offset": round(offset, 3), "disc": disc})
        offset += d
        prev = r
    return items


def build_m3u8(items: list[dict], seg_url, init_url, transcoded: bool = False) -> str:
    target = max([math.ceil(i["dur"]) for i in items] or [1])
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", f"#EXT-X-TARGETDURATION:{target}",
             "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS"]
    sess = None
    for i in items:
        if i["disc"]:
            lines.append("#EXT-X-DISCONTINUITY")
        if not transcoded and i["sess"] != sess:
            lines.append(f'#EXT-X-MAP:URI="{init_url(i["sess"])}"')
        sess = i["sess"]
        lines.append(f"#EXTINF:{i['dur']:.3f},")
        lines.append(seg_url(i))
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def keep_for_motion(seg_start: float, seg_dur: float, events, pre: float, post: float, now: float) -> bool:
    seg_end = seg_start + seg_dur
    for ev in events:
        ev_end = ev["end"] if ev["end"] is not None else now
        if seg_end >= ev["start"] - pre and seg_start <= ev_end + post:
            return True
    return False
