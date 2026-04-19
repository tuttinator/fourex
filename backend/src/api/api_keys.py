"""
API-key renewal endpoint for signed-in human players.

The 24h-expiry API key minted at ``create_game`` / ``join_game`` will time
out mid-game in long sessions. Rather than forcing the user to re-join
(which would lose their seat) the frontend can trade their Auth.js JWT
for a freshly-minted key bound to the same ``(game_id, player_id)`` row,
provided the row was originally attributed to their ``UserIdentity``.

MCP-minted keys leave ``user_identity_id`` null and therefore cannot be
renewed via this endpoint — agents mint keys through MCP directly.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import DEFAULT_KEY_TTL, generate_api_key
from ..database.connection import get_database_session
from ..database.repository import GameRepository
from ..identity import UserIdentityContext, require_user_identity

router = APIRouter()


class RenewApiKeyResponse(BaseModel):
    """Newly-minted API key + metadata returned to the caller."""

    game_id: str
    player_id: str
    api_key: str
    expires_at: str


@router.post(
    "/games/{game_id}/api-key/renew",
    response_model=RenewApiKeyResponse,
    tags=["games"],
)
async def renew_api_key(
    game_id: str,
    identity: UserIdentityContext = Depends(require_user_identity),
    session: AsyncSession = Depends(get_database_session),
    ttl: timedelta = DEFAULT_KEY_TTL,
) -> RenewApiKeyResponse:
    """Mint a fresh API key for the signed-in user's seat in this game.

    Requires a valid Auth.js JWT. Returns 404 if the user does not own a
    key in this game, 410 if the game has ended.
    """
    repo = GameRepository(session)

    game = await repo.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.status == "ended":
        raise HTTPException(
            status_code=410, detail="Game has ended — API keys cannot be renewed"
        )

    existing = await repo.get_player_api_key_by_user_identity(
        game_id=game_id, user_identity_id=identity.user_identity_id
    )
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="No API key owned by the signed-in user in this game",
        )

    plaintext = generate_api_key()
    expires_at = datetime.now(UTC).replace(tzinfo=None) + ttl
    await repo.rotate_player_api_key(existing, plaintext, expires_at)
    await session.commit()

    return RenewApiKeyResponse(
        game_id=existing.game_id,
        player_id=existing.player_id,
        api_key=plaintext,
        expires_at=expires_at.isoformat(),
    )
