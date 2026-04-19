"""
Identity management endpoints called by the Next.js frontend's Auth.js adapter.

The Next.js ``events.signIn`` callback calls ``POST /identities/upsert`` on
first successful magic-link verification so that FastAPI has a
``UserIdentity`` row to bind future ``PlayerApiKey`` rows to. The Auth.js
JWT then carries the returned ``id`` as its ``sub`` claim; the FastAPI
``verify_auth_jwt`` dependency (see ``backend/src/identity.py``) reads it
back on lobby-lifecycle requests.

This route is orthogonal to both the Auth.js JWT flow (user-facing) and the
API-key flow (gameplay). It is a server-to-server call gated by a shared
secret in the ``X-Identity-Service-Secret`` header. Rotating that secret
requires a coordinated redeploy of Next.js and FastAPI; see
``settings.identity_service_secret``.
"""

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

    Called by the Next.js Auth.js adapter on first magic-link verify and on
    every subsequent sign-in. Returns the canonical ``UserIdentity.id`` the
    frontend embeds as the JWT ``sub`` claim.
    """
    repo = GameRepository(session)
    identity = await repo.upsert_user_identity_by_email(body.email)
    await session.commit()
    return UpsertIdentityResponse(id=identity.id, email=identity.email)
