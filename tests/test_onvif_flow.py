import asyncio

import httpx
import pytest

from app.config import Camera
from app.onvif import OnvifEvents

CAPS = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tt="http://www.onvif.org/ver10/schema">
<s:Body><GetCapabilitiesResponse><Capabilities><tt:Events><tt:XAddr>http://192.168.1.10/onvif/event_service</tt:XAddr>
</tt:Events></Capabilities></GetCapabilitiesResponse></s:Body></s:Envelope>"""
CREATE = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://www.w3.org/2005/08/addressing">
<s:Body><CreatePullPointSubscriptionResponse><SubscriptionReference><a:Address>http://192.168.1.10/onvif/sub/7</a:Address>
<a:ReferenceParameters><SubscriptionId xmlns="urn:x">7</SubscriptionId></a:ReferenceParameters>
</SubscriptionReference></CreatePullPointSubscriptionResponse></s:Body></s:Envelope>"""
PULL = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
 xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body><PullMessagesResponse><wsnt:NotificationMessage>
<wsnt:Topic>tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic><wsnt:Message><tt:Message><tt:Data>
<tt:SimpleItem Name="IsMotion" Value="{v}"/></tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>
</PullMessagesResponse></s:Body></s:Envelope>"""


@pytest.mark.asyncio
async def test_subscribe_and_pull_rewrites_hosts():
    requests = []
    pulls = iter(["true", "false"])

    def handler(request: httpx.Request):
        body = request.content.decode()
        requests.append((str(request.url), body))
        if "GetSystemDateAndTime" in body:
            return httpx.Response(500)
        if "GetCapabilities" in body:
            return httpx.Response(200, text=CAPS)
        if "CreatePullPointSubscription" in body:
            return httpx.Response(200, text=CREATE)
        if "PullMessages" in body:
            try:
                return httpx.Response(200, text=PULL.format(v=next(pulls)))
            except StopIteration:
                raise httpx.ConnectError("done")
        return httpx.Response(200, text="<s:Envelope xmlns:s='http://www.w3.org/2003/05/soap-envelope'><s:Body/></s:Envelope>")

    states = []
    cam = Camera(id="c1", name="c1", host="203.0.113.5", http_port=8081, username="admin", password="pw")
    ev = OnvifEvents(cam, states.append)
    ev._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    task = asyncio.create_task(ev.run())
    for _ in range(50):
        await asyncio.sleep(0.02)
        if len(states) == 2:
            break
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert states == [True, False]
    urls = [u for u, _ in requests]
    assert "http://203.0.113.5:8081/onvif/event_service" in urls
    assert "http://203.0.113.5:8081/onvif/sub/7" in urls
    pull_body = next(b for u, b in requests if "PullMessages" in b)
    assert "SubscriptionId" in pull_body and "PasswordDigest" in pull_body
