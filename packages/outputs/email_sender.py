"""
Pluggable transactional email backend.

docs/architecture.md is explicit that Gmail SMTP is NOT acceptable for the
magic-link login path at public-product scale (deliverability failures
there mean users literally cannot log in) — Resend/Postmark/SES is the
target. This module makes that swappable without touching any caller:
callers just call send_email(); which backend actually delivers it is a
config decision (RESEND_API_KEY set or not), not a code decision.

Local dev default: ConsoleEmailBackend, which prints the email (including
the magic-link URL) to stdout instead of sending it — lets you exercise
the full auth flow with zero external email account needed.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx


class EmailBackend(ABC):
    @abstractmethod
    async def send(self, to: str, subject: str, html_body: str) -> None: ...


class ConsoleEmailBackend(EmailBackend):
    """Dev default — no external account needed. Prints the email so a
    developer can copy the magic link straight out of the terminal."""

    async def send(self, to: str, subject: str, html_body: str) -> None:
        print("\n" + "=" * 60)
        print(f"  [console-email] To: {to}")
        print(f"  Subject: {subject}")
        print("-" * 60)
        print(html_body)
        print("=" * 60 + "\n")


class ResendEmailBackend(EmailBackend):
    """Production backend — https://resend.com. One HTTP call, no SMTP
    session/quota concerns."""

    def __init__(self, api_key: str, from_address: str):
        self.api_key = api_key
        self.from_address = from_address

    async def send(self, to: str, subject: str, html_body: str) -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"from": self.from_address, "to": [to], "subject": subject, "html": html_body},
            )
            r.raise_for_status()


def get_email_backend() -> EmailBackend:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if api_key:
        from_address = os.environ.get("EMAIL_FROM", "JobFighter <onboarding@resend.dev>")
        return ResendEmailBackend(api_key, from_address)
    return ConsoleEmailBackend()
