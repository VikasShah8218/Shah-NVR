"""ONVIF PullPoint client (docs/ONVIF_EVENTS_PLAN.md §5.1): event properties, subscribe, pull, renew, unsubscribe.

Every call to the subscription address carries WS-Addressing (To, Action, MessageID) plus the ReferenceParameters
the camera gave us: Pro3/Pro4/Flex/ISIN refuse PullMessages / Renew / Unsubscribe without them (lab Q2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from lxml import etree

from app.onvif.event_topics import NS, Notification, TopicInfo, parse_notifications, parse_topic_set
from app.onvif.services import OnvifDevice, parse_capabilities, rehost
from app.onvif.soap import Fault, NotSupported, OnvifError

EVENTS_NS = NS["tev"]
_A_EV = "http://www.onvif.org/ver10/events/wsdl/EventPortType"
_A_PP = "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription"
_A_SM = "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager"
_TEV = f'xmlns:tev="{NS["tev"]}"'
_WSNT = f'xmlns:wsnt="{NS["wsnt"]}"'


class InvalidFilter(OnvifError):
    """The camera refused our topic filter (ISIN: `//.` subtrees): subscribe without one."""

    code = "fault"


@dataclass
class Subscription:
    address: str
    ref_params: str  # ReferenceParameters children, echoed as SOAP headers


def _esc(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wsa_headers(action: str, to: str, ref_params: str = "") -> str:
    return (f'<wsa:Action xmlns:wsa="{NS["wsa"]}" s:mustUnderstand="1">{action}</wsa:Action>'
            f'<wsa:MessageID xmlns:wsa="{NS["wsa"]}">urn:uuid:{uuid.uuid4()}</wsa:MessageID>'
            f'<wsa:To xmlns:wsa="{NS["wsa"]}" s:mustUnderstand="1">{_esc(to)}</wsa:To>{ref_params}')


def parse_subscription(body: etree._Element) -> tuple[str | None, str]:
    """CreatePullPointSubscriptionResponse -> (address, ReferenceParameters XML). Both WS-Addressing versions."""
    ref = body.find(".//tev:SubscriptionReference", NS)
    if ref is None:
        return None, ""
    address, params = None, ""
    for wsa in ("wsa", "wsa04"):
        address = address or (ref.findtext(f"{wsa}:Address", namespaces=NS) or "").strip() or None
        rp = ref.find(f"{wsa}:ReferenceParameters", NS)
        if rp is not None and not params:
            params = "".join(etree.tostring(c, encoding="unicode") for c in rp if isinstance(c.tag, str))
    return address, params


class EventClient:
    """`EventClient(dev)` on an open OnvifDevice whose clock offset is set (`await dev.clock()`)."""

    def __init__(self, dev: OnvifDevice):
        self.dev = dev
        self.url: str | None = None

    def fix(self, url: str) -> str:
        """The host we reached, and the device service's scheme (a camera on 443 may advertise http://: lab Q10)."""
        url = rehost(url, self.dev.host)
        scheme = urlsplit(self.dev.device_url).scheme
        u = urlsplit(url)
        if u.scheme != scheme and u.hostname == self.dev.host:
            port = u.port if u.port not in (80, 443, None) else None
            netloc = self.dev.host + (f":{port}" if port else "")
            url = urlunsplit((scheme, netloc, u.path, u.query, u.fragment))
        return url

    async def events_url(self) -> str:
        if self.url:
            return self.url
        services = await self.dev.services()
        url = services.get(EVENTS_NS)
        if not url:  # some firmware leaves services out of GetServices; GetCapabilities lists them (lab Q9)
            try:
                url = parse_capabilities(await self.dev.soap.call(
                    self.dev.device_url, "<tds:GetCapabilities><tds:Category>Events</tds:Category></tds:GetCapabilities>"
                )).get(EVENTS_NS)
            except (NotSupported, Fault):
                url = None
        if not url:
            raise NotSupported("the camera has no ONVIF event service")
        self.url = self.fix(url)
        return self.url

    async def properties(self) -> list[TopicInfo]:
        body = await self.dev.soap.call(await self.events_url(), f"<tev:GetEventProperties {_TEV}/>", timeout=20)
        return parse_topic_set(body)

    async def subscribe(self, seconds: int = 60, topic_filter: str | None = None) -> Subscription:
        filt = f"<tev:Filter>{topic_filter}</tev:Filter>" if topic_filter else ""
        try:
            body = await self.dev.soap.call(
                await self.events_url(),
                f"<tev:CreatePullPointSubscription {_TEV}>{filt}<tev:InitialTerminationTime>PT{seconds}S"
                f"</tev:InitialTerminationTime></tev:CreatePullPointSubscription>")
        except Fault as exc:
            if topic_filter and ("filter" in exc.message.lower() or "topicexpression" in exc.message.lower()):
                raise InvalidFilter(exc.message) from None
            raise
        address, params = parse_subscription(body)
        if not address:
            raise Fault("CreatePullPointSubscription: no subscription address")
        return Subscription(address=self.fix(address), ref_params=params)

    async def _sub_call(self, sub: Subscription, body: str, action: str, timeout: float | None = None) -> etree._Element:
        return await self.dev.soap.call(sub.address, body, headers=wsa_headers(action, sub.address, sub.ref_params),
                                        timeout=timeout)

    async def pull(self, sub: Subscription, wait: int = 10, limit: int = 100) -> list[Notification]:
        body = await self._sub_call(sub, f"<tev:PullMessages {_TEV}><tev:Timeout>PT{wait}S</tev:Timeout>"
                                         f"<tev:MessageLimit>{limit}</tev:MessageLimit></tev:PullMessages>",
                                    f"{_A_PP}/PullMessagesRequest", timeout=wait + 10)
        return parse_notifications(body)

    async def sync_point(self, sub: Subscription) -> None:
        await self._sub_call(sub, f"<tev:SetSynchronizationPoint {_TEV}/>", f"{_A_PP}/SetSynchronizationPointRequest")

    async def renew(self, sub: Subscription, seconds: int = 60) -> None:
        await self._sub_call(sub, f"<wsnt:Renew {_WSNT}><wsnt:TerminationTime>PT{seconds}S</wsnt:TerminationTime>"
                                  f"</wsnt:Renew>", f"{_A_SM}/RenewRequest")

    async def unsubscribe(self, sub: Subscription) -> None:
        await self._sub_call(sub, f"<wsnt:Unsubscribe {_WSNT}/>", f"{_A_SM}/UnsubscribeRequest", timeout=5)
