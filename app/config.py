"""Loading and validation of config.yaml.

Values in the form ${VAR} are substituted from environment variables, so
camera passwords can live in .env instead of the config file.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import yaml

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _expand(value):
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


@dataclass
class Camera:
    id: str
    name: str
    host: str
    username: str = ""
    password: str = ""
    rtsp_port: int = 554
    http_port: int = 80
    main_path: str = "/unicast/c1/s0/live"
    sub_path: str = "/unicast/c1/s1/live"
    # continuous = record 24/7, motion = keep only segments around motion events
    mode: str = "continuous"
    audio: bool = True
    onvif: bool = True
    enabled: bool = True
    # Full RTSP URLs override host/port/path if set
    main_url: str = ""
    sub_url: str = ""
    # Extra ffmpeg input args for the recorder (testing / special sources)
    record_input_args: list[str] = field(default_factory=list)
    record_url: str = ""

    def _rtsp(self, path: str) -> str:
        auth = ""
        if self.username:
            auth = quote(self.username, safe="") + ":" + quote(self.password, safe="") + "@"
        return f"rtsp://{auth}{self.host}:{self.rtsp_port}{path}"

    @property
    def main_rtsp(self) -> str:
        return self.main_url or self._rtsp(self.main_path)

    @property
    def sub_rtsp(self) -> str:
        return self.sub_url or self._rtsp(self.sub_path)

    @property
    def onvif_url(self) -> str:
        return f"http://{self.host}:{self.http_port}/onvif/device_service"


@dataclass
class Config:
    storage_path: Path
    data_path: Path
    retention_days: float = 14
    max_usage_percent: float = 92
    segment_seconds: int = 6
    pre_seconds: int = 10
    post_seconds: int = 20
    max_event_seconds: int = 300
    cookie_secure: bool = True
    session_days: int = 30
    go2rtc_api: str = "http://go2rtc:1984"
    go2rtc_rtsp: str = "rtsp://go2rtc:8554"
    go2rtc_config: Path | None = None
    record_via_go2rtc: bool = True
    webrtc: bool = False
    webrtc_candidates: list[str] = field(default_factory=list)
    export_max_seconds: int = 4 * 3600
    transcode_height: int = 720
    transcode_workers: int = 2
    site_name: str = "FarNVR"
    cameras: list[Camera] = field(default_factory=list)

    def camera(self, cam_id: str) -> Camera | None:
        for c in self.cameras:
            if c.id == cam_id:
                return c
        return None


def load_config(path: str | os.PathLike | None = None) -> Config:
    path = Path(path or os.environ.get("NVR_CONFIG", "/etc/nvr/config.yaml"))
    raw = _expand(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    server = raw.get("server", {}) or {}
    storage = raw.get("storage", {}) or {}
    rec = raw.get("recording", {}) or {}
    live = raw.get("live", {}) or {}

    cams: list[Camera] = []
    seen = set()
    for item in raw.get("cameras", []) or []:
        cam = Camera(**item)
        if not _ID_RE.match(cam.id):
            raise ValueError(f"Neplatné id kamery '{cam.id}' (povoleno a-z, 0-9, _ a -)")
        if cam.id in seen:
            raise ValueError(f"Duplicitní id kamery '{cam.id}'")
        if cam.mode not in ("continuous", "motion"):
            raise ValueError(f"Kamera {cam.id}: mode musí být continuous nebo motion")
        seen.add(cam.id)
        cams.append(cam)

    go2rtc_cfg = live.get("go2rtc_config")
    return Config(
        storage_path=Path(storage.get("path", "/recordings")),
        data_path=Path(server.get("data_path", "/var/lib/nvr")),
        retention_days=float(storage.get("retention_days", 14)),
        max_usage_percent=float(storage.get("max_usage_percent", 92)),
        segment_seconds=int(rec.get("segment_seconds", 6)),
        pre_seconds=int(rec.get("pre_seconds", 10)),
        post_seconds=int(rec.get("post_seconds", 20)),
        max_event_seconds=int(rec.get("max_event_seconds", 300)),
        cookie_secure=bool(server.get("cookie_secure", True)),
        session_days=int(server.get("session_days", 30)),
        site_name=str(server.get("site_name", "FarNVR")),
        export_max_seconds=int(server.get("export_max_hours", 4) * 3600),
        transcode_height=int(server.get("transcode_height", 720)),
        transcode_workers=int(server.get("transcode_workers", 2)),
        go2rtc_api=live.get("go2rtc_api", "http://go2rtc:1984").rstrip("/"),
        go2rtc_rtsp=live.get("go2rtc_rtsp", "rtsp://go2rtc:8554").rstrip("/"),
        go2rtc_config=Path(go2rtc_cfg) if go2rtc_cfg else None,
        record_via_go2rtc=bool(rec.get("via_go2rtc", True)),
        webrtc=bool(live.get("webrtc", False)),
        webrtc_candidates=list(live.get("webrtc_candidates", []) or []),
        cameras=cams,
    )
