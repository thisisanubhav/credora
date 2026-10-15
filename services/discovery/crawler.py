"""Bounded, allowlisted HTML fetching with robots and redirect safeguards."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from services.discovery.sources import require_source

USER_AGENT = "LoanEligibilityResearchBot/0.1 (contact: repository maintainers; daily public-page fetch)"
MAX_HTML_BYTES = 1_500_000
MAX_ROBOTS_BYTES = 200_000


class CrawlError(Exception):
    """A safe, stable classification without response body or source URL secrets."""


def _public_host(host: str) -> None:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise CrawlError("non_public_source_address")


def _read_limited(response: httpx.Response, limit: int) -> bytes:
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise CrawlError("response_too_large")
    return bytes(body)


def _request(client: httpx.Client, url: str, *, limit: int) -> bytes:
    for attempt in range(3):
        try:
            with client.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"}) as response:
                if response.is_redirect:
                    raise CrawlError("redirect_not_allowed")
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise CrawlError("retry_exhausted")
                if response.status_code != 200:
                    raise CrawlError(f"http_{response.status_code}")
                return _read_limited(response, limit)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            if attempt == 2:
                raise CrawlError("retry_exhausted") from error
            time.sleep(0.5 * (attempt + 1))
    raise CrawlError("retry_exhausted")


def fetch_source(key: str, *, client: httpx.Client | None = None) -> dict[str, str]:
    source = require_source(key)
    url = source.url
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port or parts.query or parts.fragment:
        raise CrawlError("unsafe_source_url")
    _public_host(parts.hostname or "")
    owned_client = client is None
    if client is None:
        client = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False, trust_env=False)
    try:
        robots_url = source.origin + "/robots.txt"
        robots_body = _request(client, robots_url, limit=MAX_ROBOTS_BYTES)
        parser = RobotFileParser()
        parser.parse(robots_body.decode("utf-8", "replace").splitlines())
        if not parser.can_fetch(USER_AGENT, url):
            raise CrawlError("robots_disallowed")
        time.sleep(1.0)
        body = _request(client, url, limit=MAX_HTML_BYTES)
        if b"<html" not in body[:1000].lower() and b"<!doctype html" not in body[:1000].lower():
            raise CrawlError("non_html_response")
        soup = BeautifulSoup(body, "html.parser")
        for element in soup(["script", "style", "noscript", "nav", "footer"]):
            element.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        start = text.casefold().find(source.eligibility_start.casefold())
        if start < 0:
            raise CrawlError("eligibility_section_missing")
        end = text.casefold().find(source.eligibility_end.casefold(), start + len(source.eligibility_start))
        if end < 0 or end - start > 4500:
            raise CrawlError("eligibility_section_unbounded")
        eligibility = text[start:end].strip()
        rate_match = re.search(r"(?:Low interest rates|Rate of interest) starting from\s*\d+(?:\.\d+)?%\*?(?:\s*p\.a\.)?", text, re.IGNORECASE)
        rate_text = rate_match.group(0).strip() if rate_match else ""
        evidence = eligibility + "\n" + rate_text
        return {
            "source_key": key, "institution": source.institution, "product_name": source.product_name,
            "source_url": url, "eligibility_text": eligibility, "interest_rate_text": rate_text,
            "source_content_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
            "retrieved_at": datetime.now(UTC).isoformat(),
        }
    finally:
        if owned_client:
            client.close()
