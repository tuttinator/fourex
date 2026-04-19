"""
Identity management endpoints called by the Next.js frontend's Auth.js adapter.

The Next.js Auth.js ``Adapter`` implementation delegates persistence to this
router: it looks up / creates ``UserIdentity`` rows on sign-in and stores
magic-link verification tokens while the Resend provider issues them. All
routes are orthogonal to both the Auth.js JWT flow (user-facing) and the
API-key flow (gameplay). They are server-to-server calls gated by a shared
secret in the ``X-Identity-Service-Secret`` header; see
``settings.identity_service_secret``.

Endpoints:
    GET  /identities/by-email        — Auth.js getUserByEmail
    GET  /identities/by-id           — Auth.js getUser / updateUser hydration
    POST /identities/upsert          — createUser / signIn upsert
    POST /identities/verification-tokens          — createVerificationToken
    POST /identities/verification-tokens/consume  — useVerificationToken
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.connection import get_database_session
from ..database.repository import GameRepository

router = APIRouter()


class UpsertIdentityRequest(BaseModel):
    email: EmailStr


class UpsertIdentityResponse(BaseModel):
    id: int
    email: str


class CreateVerificationTokenRequest(BaseModel):
    identifier: str
    token: str
    expires: datetime


class VerificationTokenResponse(BaseModel):
    identifier: str
    token: str
    expires: datetime


class ConsumeVerificationTokenRequest(BaseModel):
    identifier: str
    token: str


def require_identity_service_secret(
    x_identity_service_secret: str | None = Header(default=None),
) -> None:
    """Reject requests that don't present the shared service secret."""
    expected = settings.identity_service_secret
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity service not configured",
        )
    if not x_identity_service_secret or x_identity_service_secret != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid identity service secret",
        )


@router.get(
    "/identities/by-email",
    response_model=UpsertIdentityResponse,
    tags=["identity"],
    dependencies=[Depends(require_identity_service_secret)],
)
async def get_identity_by_email(
    email: EmailStr,
    session: AsyncSession = Depends(get_database_session),
) -> UpsertIdentityResponse:
    """Return the UserIdentity for a normalised email, or 404 if missing.

    Auth.js calls this from its ``getUserByEmail`` adapter method before the
    Resend provider issues a magic link. 404 tells the adapter to call
    ``createUser`` next; this router exposes that path as ``/upsert``.
    """
    repo = GameRepository(session)
    identity = await repo.get_user_identity_by_email(email)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return UpsertIdentityResponse(id=identity.id, email=identity.email)


@router.get(
    "/identities/by-id",
    response_model=UpsertIdentityResponse,
    tags=["identity"],
    dependencies=[Depends(require_identity_service_secret)],
)
async def get_identity_by_id(
    id: int,
    session: AsyncSession = Depends(get_database_session),
) -> UpsertIdentityResponse:
    """Return the UserIdentity for a primary-key id, or 404 if missing.

    Auth.js calls this from its ``getUser`` and ``updateUser`` adapter methods
    when resolving an existing session or marking an email verified. The
    adapter only receives ``{id, ...}`` in those hooks, so it re-hydrates the
    full row here instead of caching state across requests.
    """
    repo = GameRepository(session)
    identity = await repo.get_user_identity_by_id(id)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return UpsertIdentityResponse(id=identity.id, email=identity.email)


@router.post(
    "/identities/upsert",
    response_model=UpsertIdentityResponse,
    tags=["identity"],
    dependencies=[Depends(require_identity_service_secret)],
)
async def upsert_identity(
    body: UpsertIdentityRequest,
    session: AsyncSession = Depends(get_database_session),
) -> UpsertIdentityResponse:
    """Look up or create the UserIdentity for a verified email.

    Called by the Next.js Auth.js adapter's ``createUser`` and on first
    magic-link verify. Returns the canonical ``UserIdentity.id`` the
    frontend embeds as the JWT ``sub`` claim.
    """
    repo = GameRepository(session)
    identity = await repo.upsert_user_identity_by_email(body.email)
    await session.commit()
    return UpsertIdentityResponse(id=identity.id, email=identity.email)


@router.post(
    "/identities/verification-tokens",
    response_model=VerificationTokenResponse,
    tags=["identity"],
    dependencies=[Depends(require_identity_service_secret)],
)
async def create_verification_token(
    body: CreateVerificationTokenRequest,
    session: AsyncSession = Depends(get_database_session),
) -> VerificationTokenResponse:
    """Persist an Auth.js magic-link verification token."""
    repo = GameRepository(session)
    row = await repo.create_verification_token(
        identifier=body.identifier,
        token=body.token,
        expires_at=(
            body.expires.replace(tzinfo=None) if body.expires.tzinfo else body.expires
        ),
    )
    await session.commit()
    return VerificationTokenResponse(
        identifier=row.identifier, token=row.token, expires=row.expires_at
    )


@router.post(
    "/identities/verification-tokens/consume",
    response_model=VerificationTokenResponse,
    tags=["identity"],
    dependencies=[Depends(require_identity_service_secret)],
)
async def consume_verification_token(
    body: ConsumeVerificationTokenRequest,
    session: AsyncSession = Depends(get_database_session),
) -> VerificationTokenResponse:
    """Atomically look up and delete the (identifier, token) row.

    Returns 404 if the row does not exist; the Auth.js adapter translates
    that into ``useVerificationToken`` returning ``null``, which makes the
    framework reject the magic link. Expired rows are returned here; the
    framework itself enforces expiry.
    """
    repo = GameRepository(session)
    row = await repo.consume_verification_token(body.identifier, body.token)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    await session.commit()
    return VerificationTokenResponse(
        identifier=row.identifier, token=row.token, expires=row.expires_at
    )
