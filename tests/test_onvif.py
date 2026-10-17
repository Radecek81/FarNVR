from app.onvif import parse_motion, rewrite_host, security_header
from datetime import datetime, timezone

PULL = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
 xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:tet="http://www.onvif.org/ver10/events/wsdl">
<s:Body><tet:PullMessagesResponse>
<wsnt:NotificationMessage>
 <wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet">tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic>
 <wsnt:Message><tt:Message UtcTime="2026-10-17T08:00:00Z" PropertyOperation="Changed">
  <tt:Source><tt:SimpleItem Name="VideoSourceConfigurationToken" Value="1"/></tt:Source>
  <tt:Data><tt:SimpleItem Name="IsMotion" Value="true"/></tt:Data>
 </tt:Message></wsnt:Message>
</wsnt:NotificationMessage>
<wsnt:NotificationMessage>
 <wsnt:Topic>tns1:VideoSource/MotionAlarm</wsnt:Topic>
 <wsnt:Message><tt:Message><tt:Data><tt:SimpleItem Name="State" Value="false"/></tt:Data></tt:Message></wsnt:Message>
</wsnt:NotificationMessage>
<wsnt:NotificationMessage>
 <wsnt:Topic>tns1:Device/Trigger/DigitalInput</wsnt:Topic>
 <wsnt:Message><tt:Message><tt:Data><tt:SimpleItem Name="LogicalState" Value="true"/></tt:Data></tt:Message></wsnt:Message>
</wsnt:NotificationMessage>
</tet:PullMessagesResponse></s:Body></s:Envelope>"""


def test_parse_motion():
    assert parse_motion(PULL) == [True, False]


def test_rewrite_host():
    assert rewrite_host("http://192.168.1.13/onvif/Events/PullSubManager?x=1", "203.0.113.5", 8081) == \
        "http://203.0.113.5:8081/onvif/Events/PullSubManager?x=1"


def test_security_header_contains_digest():
    h = security_header("admin", "secret", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert "PasswordDigest" in h and "<Username>admin</Username>" in h and "2026-01-01T00:00:00.000Z" in h
