"""Minimal ONVIF event client (PullPoint) for motion detection.

Only what the NVR needs: discover the event service, create a PullPoint
subscription, pull messages and turn motion topics into start/stop calls.
Written by hand (no zeep) to stay small and dependency free.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from xml.sax.saxutils import escape

import httpx

from .config import Camera

log = logging.getLogger("nvr.onvif")

NS_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
NS_WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
PW_DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
B64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-soap-message-security-1.0#Base64Binary"

ACT_CREATE = "http://www.onvif.org/ver10/events/wsdl/EventPortType/CreatePullPointSubscriptionRequest"
ACT_PULL = "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
ACT_RENEW = "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/RenewRequest"
ACT_UNSUB = "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/UnsubscribeRequest"


class OnvifError(Exception):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el: ET.Element, name: str) -> ET.Element | None:
    for x in el.iter():
        if _local(x.tag) == name:
            return x
    return None


def _findall(el: ET.Element, name: str) -> list[ET.Element]:
    return [x for x in el.iter() if _local(x.tag) == name]


def rewrite_host(url: str, host: str, port: int) -> str:
    """Cameras behind port forwarding report their LAN address; replace it."""
    p = urlsplit(url)
    return urlunsplit((p.scheme or "http", f"{host}:{port}", p.path, p.query, p.fragment))


def security_header(username: str, password: str, created: datetime) -> str:
    nonce = os.urandom(16)
    created_s = created.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    digest = base64.b64encode(hashlib.sha1(nonce + created_s.encode() + password.encode()).digest()).decode()
    return (
        f'<Security s:mustUnderstand="1" xmlns="{NS_WSSE}"><UsernameToken>'
        f"<Username>{escape(username)}</Username>"
        f'<Password Type="{PW_DIGEST}">{digest}</Password>'
        f'<Nonce EncodingType="{B64}">{base64.b64encode(nonce).decode()}</Nonce>'
        f'<Created xmlns="{NS_WSU}">{created_s}</Created>'
        "</UsernameToken></Security>"
    )


def parse_motion(xml: bytes | str) -> list[bool]:
    """Return motion states (True=start, False=stop) found in a PullMessages response."""
    root = ET.fromstring(xml)
    states: list[bool] = []
    for msg in _findall(root, "NotificationMessage"):
        topic_el = _find(msg, "Topic")
        topic = (topic_el.text or "").lower() if topic_el is not None else ""
        if "motion" not in topic:
            continue
        data = _find(msg, "Data")
        if data is None:
            continue
        for item in _findall(data, "SimpleItem"):
            name = (item.get("Name") or "").lower()
            if name in ("ismotion", "state", "value", "motion", "motionactive"):
                states.append((item.get("Value") or "").strip().lower() in ("true", "1", "on"))
                break
    return states


class OnvifEvents:
    def __init__(self, cam: Camera, on_motion: Callable[[bool], None]):
        self.cam = cam
        self.on_motion = on_motion
        self.state = "idle"
        self.last_error = ""
        self.last_event_at = 0.0
        self._offset = timedelta(0)
        self._digest = False
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0))

    def _envelope(self, body: str, action: str | None = None, to: str | None = None,
                  ref_params: str = "", auth: bool = True) -> str:
        header = ""
        if auth and self.cam.username:
            header += security_header(self.cam.username, self.cam.password,
                                      datetime.now(timezone.utc) + self._offset)
        if action:
            header += f"<a:Action s:mustUnderstand=\"1\">{action}</a:Action>"
        if to:
            header += f"<a:To s:mustUnderstand=\"1\">{escape(to)}</a:To>"
        header += ref_params
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
                'xmlns:a="http://www.w3.org/2005/08/addressing">'
                f"<s:Header>{header}</s:Header><s:Body>{body}</s:Body></s:Envelope>")

    async def _call(self, url: str, body: str, **kw) -> ET.Element:
        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
        data = self._envelope(body, **kw).encode()
        auth = httpx.DigestAuth(self.cam.username, self.cam.password) if self._digest else None
        r = await self._client.post(url, content=data, headers=headers, auth=auth)
        if r.status_code == 401 and not self._digest and self.cam.username:
            self._digest = True
            r = await self._client.post(url, content=self._envelope(body, **kw).encode(), headers=headers,
                                        auth=httpx.DigestAuth(self.cam.username, self.cam.password))
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            raise OnvifError(f"HTTP {r.status_code}: neplatná odpověď")
        fault = _find(root, "Fault")
        if fault is not None or r.status_code >= 400:
            text = " ".join(t.strip() for t in fault.itertext() if t.strip()) if fault is not None else ""
            raise OnvifError(f"HTTP {r.status_code}: {text[:200]}")
        return root

    async def _sync_time(self, device_url: str):
        body = '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>'
        try:
            root = await self._call(device_url, body, auth=False)
        except (OnvifError, httpx.HTTPError):
            return
        utc = _find(root, "UTCDateTime")
        if utc is None:
            return
        vals = {}
        for k in ("Year", "Month", "Day", "Hour", "Minute", "Second"):
            el = _find(utc, k)
            vals[k] = int(el.text) if el is not None and el.text else 0
        try:
            cam_time = datetime(vals["Year"], vals["Month"], vals["Day"], vals["Hour"], vals["Minute"],
                                vals["Second"], tzinfo=timezone.utc)
            self._offset = cam_time - datetime.now(timezone.utc)
        except ValueError:
            pass

    async def _subscribe(self) -> tuple[str, str]:
        device_url = self.cam.onvif_url
        await self._sync_time(device_url)
        root = await self._call(device_url, '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl">'
                                            '<Category>Events</Category></GetCapabilities>')
        events = _find(root, "Events")
        xaddr_el = _find(events, "XAddr") if events is not None else None
        if xaddr_el is None or not xaddr_el.text:
            raise OnvifError("Kamera nehlásí Events službu")
        ev_url = rewrite_host(xaddr_el.text.strip(), self.cam.host, self.cam.http_port)
        root = await self._call(ev_url, '<CreatePullPointSubscription xmlns="http://www.onvif.org/ver10/events/wsdl">'
                                        '<InitialTerminationTime>PT600S</InitialTerminationTime>'
                                        '</CreatePullPointSubscription>', action=ACT_CREATE, to=ev_url)
        ref = _find(root, "SubscriptionReference")
        addr = _find(ref, "Address") if ref is not None else None
        if addr is None or not addr.text:
            raise OnvifError("CreatePullPointSubscription bez adresy")
        sub_url = rewrite_host(addr.text.strip(), self.cam.host, self.cam.http_port)
        params = ""
        rp = _find(ref, "ReferenceParameters")
        if rp is not None:
            params = "".join(ET.tostring(child, encoding="unicode") for child in rp)
        return sub_url, params

    async def run(self):
        backoff = 5
        while True:
            sub_url = None
            params = ""
            try:
                self.state = "connecting"
                sub_url, params = await self._subscribe()
                self.state = "subscribed"
                self.last_error = ""
                backoff = 5
                renewed = time.monotonic()
                while True:
                    root = await self._call(
                        sub_url, '<PullMessages xmlns="http://www.onvif.org/ver10/events/wsdl">'
                                 '<Timeout>PT20S</Timeout><MessageLimit>32</MessageLimit></PullMessages>',
                        action=ACT_PULL, to=sub_url, ref_params=params)
                    for active in parse_motion(ET.tostring(root)):
                        self.last_event_at = time.time()
                        self.on_motion(active)
                    if time.monotonic() - renewed > 240:
                        await self._call(sub_url, '<Renew xmlns="http://docs.oasis-open.org/wsn/b-2">'
                                                  '<TerminationTime>PT600S</TerminationTime></Renew>',
                                         action=ACT_RENEW, to=sub_url, ref_params=params)
                        renewed = time.monotonic()
            except asyncio.CancelledError:
                if sub_url:
                    await self._unsubscribe(sub_url, params)
                await self._client.aclose()
                raise
            except Exception as exc:
                self.state = "error"
                self.last_error = str(exc)[:300]
                log.warning("%s: ONVIF events: %s", self.cam.id, exc)
                if sub_url:
                    await self._unsubscribe(sub_url, params)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    async def _unsubscribe(self, sub_url: str, params: str):
        try:
            await self._call(sub_url, '<Unsubscribe xmlns="http://docs.oasis-open.org/wsn/b-2"/>',
                             action=ACT_UNSUB, to=sub_url, ref_params=params)
        except Exception:
            pass
