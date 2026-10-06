"""SSRF protection for URLs found in course content (link checker, oEmbed lookups).

Adapted from the KI-vurderingsstøtte project.

Rules (see docs/THREAT_MODEL.md):

* only ``http``/``https``; no credentials in the URL; only ports 80/443;
* hostnames that are obviously internal (localhost, *.local, *.internal ...)
  are refused before any DNS lookup;
* every resolved address must be globally routable. Loopback, RFC 1918,
  link-local (incl. cloud metadata 169.254.169.254), CGNAT, multicast,
  reserved, unspecified and IPv6 equivalents are refused - including
  IPv4-mapped, 6to4, Teredo and NAT64 encodings of such addresses;
* the check is done *at connect time* inside the HTTP client's network
  backend and the socket connects to the validated IP, so a DNS answer that
  changes between check and use (DNS rebinding) cannot bypass it;
* redirects are followed manually and every hop is validated again.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
INTERNAL_SUFFIXES = (
    ".localhost", ".local", ".internal", ".intranet", ".lan", ".home", ".home.arpa", ".corp",
    ".localdomain", ".test", ".invalid",
)
EXTRA_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
        "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
        "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8", "2001:db8::/32", "100::/64",
    )
]
NAT64 = ipaddress.ip_network("64:ff9b::/96")


class UrlBlocked(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def is_public_ip(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    try:
        ip = ipaddress.ip_address(value) if isinstance(value, str) else value
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.scope_id:
            return False
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return is_public_ip(ip.sixtofour)
        if ip.teredo is not None:
            return False
        if ip in NAT64:
            return is_public_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if any(ip in net for net in EXTRA_BLOCKED_NETWORKS if net.version == ip.version):
        return False
    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    scheme: str
    host: str
    port: int


def validate_url(url: str) -> ValidatedUrl:
    url = (url or "").strip()
    if len(url) > 2048:
        raise UrlBlocked("url_too_long", "Adressen er for lang.")
    if any(ch in url for ch in "\r\n\t\x00 "):
        raise UrlBlocked("url_invalid", "Adressen inneholder ugyldige tegn.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UrlBlocked("url_invalid", "Adressen er ugyldig.") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlBlocked("url_scheme", f"Bare http og https er tillatt (ikke «{scheme or 'ingen'}»).")
    if parts.username or parts.password:
        raise UrlBlocked("url_credentials", "Adresser med brukernavn eller passord hentes ikke.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UrlBlocked("url_invalid", "Adressen mangler vertsnavn.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UrlBlocked("url_invalid", "Vertsnavnet er ugyldig.") from exc
    port = port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UrlBlocked("url_port", "Bare standardportene 80 og 443 er tillatt.")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_ip(literal):
            raise UrlBlocked("url_private_ip", "Adressen peker til et privat eller internt nettverk.")
    elif host == "localhost" or host.endswith(INTERNAL_SUFFIXES) or "." not in host:
        raise UrlBlocked("url_internal", "Interne adresser og lokale vertsnavn hentes ikke.")
    return ValidatedUrl(url=url, scheme=scheme, host=host, port=port)


async def resolve_public(host: str, port: int) -> list[str]:
    """Resolve ``host`` and return its addresses - only if *all* are public."""
    host = host.strip("[]")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_ip(literal):
            raise UrlBlocked("url_private_ip", "Adressen peker til et privat eller internt nettverk.")
        return [str(literal)]
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlBlocked("url_dns", "Fant ikke nettstedet (DNS-oppslag feilet).") from exc
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses:
        raise UrlBlocked("url_dns", "Fant ikke nettstedet.")
    blocked = [a for a in addresses if not is_public_ip(a)]
    if blocked:
        raise UrlBlocked("url_private_ip", "Nettstedet peker til et privat eller internt nettverk.")
    return addresses
