"""Helpers for Phase 5 lobby invite tokens and email delivery.

This module contains the pure parts of the invite flow:

* Token minting / hashing (``mint_invite_token``).
* Building the redemption URL embedded in the email
  (``build_invite_url``).
* Calling Resend's HTTP API to deliver the invite
  (``send_invite_email``).

The REST endpoints under ``rest.py`` orchestrate these helpers,
persist the row via the repository, and broadcast the lobby state.

Tokens are 32-byte URL-safe random strings; only the SHA-256 hash is
persisted, mirroring the ``PlayerApiKey`` invariant. Resend delivery
is deliberately fire-and-forget at the orchestration layer — a
delivery failure raises ``InviteEmailError`` and the caller decides
whether to surface it as 502 or roll back; this module does not
swallow failures.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from ..config import settings

INVITE_TTL_SECONDS = 24 * 60 * 60
RESEND_API_URL = "https://api.resend.com/emails"


class InviteEmailError(RuntimeError):
    """Raised when Resend rejects an invite email send."""


@dataclass(frozen=True)
class MintedInvite:
    """A freshly minted invite token plus its hash + expiry.

    The plaintext is returned so the caller can build the redemption
    URL; only ``token_hash`` is persisted.
    """

    plaintext: str
    token_hash: str
    expires_at: datetime


def mint_invite_token(now: datetime | None = None) -> MintedInvite:
    """Mint a fresh single-use token + hash + expiry."""
    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_invite_token(plaintext)
    base = now or datetime.now(UTC).replace(tzinfo=None)
    return MintedInvite(
        plaintext=plaintext,
        token_hash=token_hash,
        expires_at=base + timedelta(seconds=INVITE_TTL_SECONDS),
    )


def hash_invite_token(plaintext: str) -> str:
    """Return the SHA-256 hex hash of an invite token."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def build_invite_url(game_id: str, token: str, base_url: str | None = None) -> str:
    """Build the lobby URL with the ``?invite=<token>`` redemption param."""
    base = (base_url or settings.frontend_base_url).rstrip("/")
    qs = urlencode({"invite": token})
    return f"{base}/games/{quote(game_id, safe='')}?{qs}"


async def send_invite_email(
    *,
    to_email: str,
    inviter_email: str | None,
    game_id: str,
    invite_url: str,
    api_key: str | None = None,
    sender: str | None = None,
) -> None:
    """Send the invite via Resend's HTTP API.

    Resend's response body is small JSON; we read it only on failure
    so the caller gets the diagnostic in the exception message. The
    function is async so the FastAPI request handler doesn't block on
    the upstream round-trip.
    """
    key = api_key if api_key is not None else settings.resend_api_key
    if not key:
        raise InviteEmailError("Resend API key is not configured")

    from_address = sender or settings.invite_email_from
    inviter_label = inviter_email or "A friend"
    subject = f"You've been invited to a Parley game ({game_id})"
    text_body = (
        f"{inviter_label} invited you to join their Parley game "
        f"({game_id}).\n\n"
        f"Click the link below to claim your seat:\n\n"
        f"{invite_url}\n\n"
        f"This invite is single-use and expires in 24 hours."
    )
    html_body = (
        f"<p>{inviter_label} invited you to join their Parley game "
        f"(<strong>{game_id}</strong>).</p>"
        f'<p><a href="{invite_url}">Click here to claim your seat.</a></p>'
        f"<p>This invite is single-use and expires in 24 hours.</p>"
    )
    payload: dict[str, Any] = {
        "from": from_address,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 300:
        raise InviteEmailError(
            f"Resend rejected invite send: {response.status_code} {response.text}"
        )
