from app.timeline import (build_m3u8, keep_for_motion, merge_intervals, parse_live_playlist,
                          select_playback)

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-MAP:URI="init.mp4"
#EXTINF:4.000000,
#EXT-X-PROGRAM-DATE-TIME:2026-10-17T07:09:32.439+0000
/rec/cam1/2026-10-17/070932-abc.m4s
#EXTINF:4.200000,
#EXT-X-PROGRAM-DATE-TIME:2026-10-17T07:09:36.439+0000
/rec/cam1/2026-10-17/070937-abc.m4s
"""


def test_parse_live_playlist():
    init, entries = parse_live_playlist(PLAYLIST)
    assert init == "init.mp4"
    assert len(entries) == 2
    assert entries[0].start == 1792220972.439
    assert entries[1].duration == 4.2
    assert entries[1].uri.endswith("070937-abc.m4s")


def test_merge_intervals_detects_gaps():
    rows = [(0, 6), (6, 6), (12.5, 6), (30, 6)]
    assert merge_intervals(rows, 0, 100) == [[0, 18.5], [30, 36]]
    assert merge_intervals(rows, 3, 33) == [[3, 18.5], [30, 33]]


def _row(i, sess, start, dur=6.0):
    return {"id": i, "sess": sess, "start": start, "duration": dur}


def test_select_playback_offsets_and_discontinuities():
    rows = [_row(1, "a", 0), _row(2, "a", 6), _row(3, "b", 20), _row(4, "b", 26)]
    items = select_playback(rows, 5, 30)
    assert [i["id"] for i in items] == [1, 2, 3, 4]
    assert [i["offset"] for i in items] == [0, 6, 12, 18]
    assert [i["disc"] for i in items] == [False, False, True, False]
    text = build_m3u8(items, lambda i: f"/s/{i['id']}", lambda s: f"/i/{s}")
    assert text.count("#EXT-X-MAP") == 2
    assert text.count("#EXT-X-DISCONTINUITY") == 1
    assert text.strip().endswith("#EXT-X-ENDLIST")


def test_keep_for_motion():
    events = [{"start": 100, "end": 110}]
    assert keep_for_motion(85, 6, events, 10, 20, 1000)       # pre-roll
    assert keep_for_motion(128, 6, events, 10, 20, 1000)      # post-roll
    assert not keep_for_motion(60, 6, events, 10, 20, 1000)
    assert not keep_for_motion(140, 6, events, 10, 20, 1000)
    assert keep_for_motion(500, 6, [{"start": 490, "end": None}], 10, 20, 505)
