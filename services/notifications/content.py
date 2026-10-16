"""Source-grounded, escaped notification text; no applicant financial fields."""

from __future__ import annotations

import hashlib
import html
import os
import re
import uuid
from typing import Any
from urllib.parse import urlsplit

DISCLAIMER = "These are potential matches, not guaranteed loan approvals."
TEMPLATE_VERSION = "potential-v1"


def recipient_for(user_id: uuid.UUID) -> str:
    """Never derive a delivery address from CSV data."""
    if os.environ.get("NOTIFICATION_MODE") != "test":
        raise ValueError("production_recipient_delivery_disabled")
    configured = os.environ.get("NOTIFICATION_TEST_EMAIL", "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", configured):
        raise ValueError("test_recipient_unconfigured")
    # SES sandbox recipients must match a verified identity exactly. In
    # particular, a Gmail plus-address is not the same SES email identity.
    if transport_mode() == "ses":
        return configured
    local, domain = configured.rsplit("@", 1)
    if domain in {"gmail.com", "googlemail.com"}:
        return f"{local.split('+', 1)[0]}+loan-{str(user_id)[:8]}@{domain}"
    return configured


def transport_mode() -> str:
    mode = os.environ.get("NOTIFICATION_TRANSPORT", "mock")
    if mode not in {"mock", "ses"}:
        raise ValueError("invalid_notification_transport")
    if mode == "ses":
        if os.environ.get("NOTIFICATION_SES_ENABLED") != "1":
            raise ValueError("ses_not_explicitly_enabled")
        if any(os.environ.get(key, "").endswith("@example.invalid") for key in
               ("NOTIFICATION_TEST_EMAIL", "NOTIFICATION_FROM_EMAIL")):
            raise ValueError("ses_placeholder_identity")
    return mode


def idempotency_key(batch_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{batch_id}:{user_id}:{TEMPLATE_VERSION}".encode()).hexdigest()


def render(products: list[dict[str, Any]], *, synthetic: bool) -> dict[str, str]:
    if not products:
        raise ValueError("no_eligible_products")
    lines: list[str] = []
    entries: list[str] = []
    for item in products:
        name = str(item["name"])
        institution = str(item["institution"])
        url = str(item["source_url"])
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid_product_source_url")
        if item["source_type"] == "synthetic":
            label = "SYNTHETIC DEMONSTRATION — NOT A REAL LENDER OFFER"
        elif item["source_type"] == "official":
            label = "Official source"
        else:
            raise ValueError("untrusted_product_source_type")
        rate = str(item["rate"]) if item.get("rate") else "Interest rate not published in the verified record"
        lines.append(f"- {institution}: {name}\n  {label}\n  {rate}\n  Source: {url}")
        entries.append("<li><strong>" + html.escape(institution) + ": " + html.escape(name)
                       + "</strong><br>" + html.escape(label) + "<br>" + html.escape(rate)
                       + '<br><a href="' + html.escape(url, quote=True) + '">Official source / fixture</a></li>')
    heading = "Synthetic demonstration matches" if synthetic else "Potential personal-loan matches"
    text = f"Hello,\n\n{heading}:\n\n" + "\n".join(lines) + f"\n\n{DISCLAIMER}\n"
    body_html = ("<!doctype html><html><body><p>Hello,</p><h2>" + html.escape(heading)
                 + "</h2><ul>" + "".join(entries) + "</ul><p>" + html.escape(DISCLAIMER)
                 + "</p></body></html>")
    return {"subject": heading, "text": text, "html": body_html}
