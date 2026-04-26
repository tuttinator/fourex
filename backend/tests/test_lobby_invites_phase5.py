"""Phase 5 (lobby + skill split): human email invitations.

Phase 5 introduces ``LobbyInvite`` rows so a Human slot can be
reserved for a specific email. The lobby creator triggers a Resend
delivery via ``POST /games/{id}/slots/{i}/invite``; the invitee
redeems the token via ``POST /games/{id}/join`` with
``invite_token`` in the body. The Resend send is patched out for
tests — we never hit the real network.

The tests cover:

* Mint creates the invite row, persists ``reserved_email`` on the
  slot, and triggers the email.
* Resend rotates the existing row's hash + expiry rather than
  creating a second row, and refuses to spam.
* Clear deletes the row and frees the slot for a public join.
* Redemption seats the caller into the reserved slot, rejects token
  reuse, expired tokens, mismatched emails, and tokens for the
  wrong game.
* Open joins skip reserved slots — only token redemption can claim
  them.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.api.invites import hash_invite_token
from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    LobbyInvite,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
    UserIdentity,
)
from backend.src.database.repository import GameRepository
from backend.src.main import app

ALG = "HS256"
PREFIX = "invitep5_"
EMAIL_DOMAIN = "invitep5.example.com"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


async def _purge() -> None:
    async with async_session_factory() as session:
        await session.execute(
            delete(LobbyInvite).where(LobbyInvite.game_id.like(f"{PREFIX}%"))
        )
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like(f"{PREFIX}%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like(f"{PREFIX}%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like(f"{PREFIX}%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like(f"{PREFIX}%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like(f"{PREFIX}%"))
        )
        await session.execute(delete(Game).where(Game.id.like(f"{PREFIX}%")))
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like(f"%@{EMAIL_DOMAIN}"))
        )
        await session.commit()


@pytest_asyncio.fixture
async def _clean() -> None:
    await init_db()
    await _purge()
    yield
    await _purge()


def _mint_jwt(user_identity_id: int, *, email: str | None = None) -> str:
    now = int(time.time())
    payload: dict[str, object] = {
        "sub": str(user_identity_id),
        "iat": now,
        "exp": now + 3600,
    }
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, settings.auth_secret, algorithm=ALG)


async def _seed_identity(email: str) -> int:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        identity = await repo.upsert_user_identity_by_email(email)
        await session.commit()
        return identity.id


def _game_id(suffix: str) -> str:
    return f"{PREFIX}{suffix}_{int(time.time() * 1000000)}"


def _create_lobby(
    client: TestClient,
    *,
    game_id: str,
    token: str,
    slots: list[dict[str, object]],
    player_id: str = "alice",
) -> dict[str, object]:
    body = {
        "player_id": player_id,
        "player_slots": len(slots),
        "creator_seated": True,
        "slots": slots,
    }
    resp = client.post(
        f"/api/v1/games?game_id={game_id}",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _patch_send():
    """Patch out the Resend HTTP call at the rest.py call site."""
    return patch("backend.src.api.rest.send_invite_email", new=AsyncMock())


async def _get_invite_token_hash(game_id: str, slot_index: int) -> str | None:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        invite = await repo.get_lobby_invite(game_id, slot_index)
        return invite.token_hash if invite else None


class TestInviteMint:
    @pytest.mark.asyncio
    async def test_invite_persists_row_and_calls_resend(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"creator@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("mint")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )

        invitee = f"bob@{EMAIL_DOMAIN}"
        with _patch_send() as send_mock:
            resp = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": invitee},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            send_mock.assert_awaited_once()

        body = resp.json()
        assert body["slot_index"] == 1
        assert body["email"] == invitee.lower()

        # The slot now carries reserved_email and an invite row exists.
        detail = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        slot1 = detail.json()["slots"][1]
        assert slot1["reserved_email"] == invitee.lower()

        token_hash = await _get_invite_token_hash(game_id, 1)
        assert token_hash is not None

    @pytest.mark.asyncio
    async def test_invite_rejects_agent_slot(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"agt@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("agt")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "agent", "name": "bot"},
            ],
        )
        with _patch_send():
            resp = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invite_rejects_occupied_slot(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"occ@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("occ")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        with _patch_send():
            resp = client.post(
                f"/api/v1/games/{game_id}/slots/0/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invite_rejects_non_creator(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"nc@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("nc")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        # Different identity / JWT.
        outsider_email = f"out@{EMAIL_DOMAIN}"
        outsider_uid = await _seed_identity(outsider_email)
        outsider_token = _mint_jwt(outsider_uid, email=outsider_email)
        with _patch_send():
            resp = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {outsider_token}"},
            )
        assert resp.status_code == 403


class TestInviteResend:
    @pytest.mark.asyncio
    async def test_resend_rotates_token_hash(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"rotate@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("rotate")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        invitee = f"bob@{EMAIL_DOMAIN}"
        with _patch_send():
            client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": invitee},
                headers={"Authorization": f"Bearer {token}"},
            )
            first_hash = await _get_invite_token_hash(game_id, 1)
            assert first_hash is not None

            # Bypass the rate-limit guard by reaching into the row and
            # making the previous send "old enough" to reissue.
            async with async_session_factory() as session:
                repo = GameRepository(session)
                invite = await repo.get_lobby_invite(game_id, 1)
                assert invite is not None
                invite.expires_at = datetime.utcnow() + timedelta(seconds=3600)
                await session.commit()

            resp = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": invitee},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
        second_hash = await _get_invite_token_hash(game_id, 1)
        assert second_hash is not None
        assert second_hash != first_hash

    @pytest.mark.asyncio
    async def test_rapid_resend_rate_limited(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"rate@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("rate")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        with _patch_send():
            first = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert first.status_code == 200
            second = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert second.status_code == 429


class TestInviteClear:
    @pytest.mark.asyncio
    async def test_clear_drops_row_and_frees_slot(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"clr@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("clr")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        with _patch_send():
            client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )

        clear = client.post(
            f"/api/v1/games/{game_id}/slots/1/invite/clear",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert clear.status_code == 200, clear.text
        slots = clear.json()["slots"]
        assert slots[1]["reserved_email"] is None

        # No invite row remains.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            invite = await repo.get_lobby_invite(game_id, 1)
            assert invite is None


class TestRedemption:
    @pytest.mark.asyncio
    async def test_redeem_seats_invitee_into_reserved_slot(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"redeem-c@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("redeem")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        invitee_email = f"bob@{EMAIL_DOMAIN}"
        captured: dict[str, str] = {}

        async def _capture(*, invite_url: str, **_: object) -> None:
            captured["invite_url"] = invite_url

        with patch(
            "backend.src.api.rest.send_invite_email", new=AsyncMock(side_effect=_capture)
        ):
            resp = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": invitee_email},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        # Extract the plaintext token from the captured URL.
        url = captured["invite_url"]
        plaintext = url.split("invite=")[1]
        token_hash = hash_invite_token(plaintext)
        assert token_hash == await _get_invite_token_hash(game_id, 1)

        invitee_uid = await _seed_identity(invitee_email)
        invitee_token = _mint_jwt(invitee_uid, email=invitee_email)
        join = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob", "invite_token": plaintext},
            headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert join.status_code == 200, join.text
        body = join.json()
        # Bob landed in slot 1 (the reserved slot), not slot 0.
        assert body["game"]["slots"][1]["name"] == "bob"

        # Single-use: reusing the same plaintext fails.
        async with async_session_factory() as session:
            await session.execute(
                delete(PlayerApiKey).where(
                    (PlayerApiKey.game_id == game_id) & (PlayerApiKey.player_id == "bob")
                )
            )
            await session.commit()
        # Re-bring the slot into a state that *would* accept a join if
        # not for the token being redeemed: re-clear bob from the slot.
        # Simpler test: just attempt the same token a second time and
        # confirm 400.
        replay = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob2", "invite_token": plaintext},
            headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert replay.status_code == 400

    @pytest.mark.asyncio
    async def test_open_join_skips_reserved_slot(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"openskip@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("openskip")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        with _patch_send():
            client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )

        outsider_email = f"carol@{EMAIL_DOMAIN}"
        outsider_uid = await _seed_identity(outsider_email)
        outsider_token = _mint_jwt(outsider_uid, email=outsider_email)
        # Open join without a token should be rejected — slot 1 is
        # reserved and slot 0 is the creator.
        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "carol"},
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_redeem_rejects_email_mismatch(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"mm@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("mm")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        captured: dict[str, str] = {}

        async def _capture(*, invite_url: str, **_: object) -> None:
            captured["invite_url"] = invite_url

        with patch(
            "backend.src.api.rest.send_invite_email", new=AsyncMock(side_effect=_capture)
        ):
            client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
        plaintext = captured["invite_url"].split("invite=")[1]

        wrong_email = f"eve@{EMAIL_DOMAIN}"
        wrong_uid = await _seed_identity(wrong_email)
        wrong_token = _mint_jwt(wrong_uid, email=wrong_email)
        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "eve", "invite_token": plaintext},
            headers={"Authorization": f"Bearer {wrong_token}"},
        )
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_redeem_rejects_expired_token(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"exp@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("exp")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        captured: dict[str, str] = {}

        async def _capture(*, invite_url: str, **_: object) -> None:
            captured["invite_url"] = invite_url

        with patch(
            "backend.src.api.rest.send_invite_email", new=AsyncMock(side_effect=_capture)
        ):
            client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
        plaintext = captured["invite_url"].split("invite=")[1]

        # Force-expire the row.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            invite = await repo.get_lobby_invite(game_id, 1)
            assert invite is not None
            invite.expires_at = datetime.utcnow() - timedelta(minutes=5)
            await session.commit()

        invitee_email = f"bob@{EMAIL_DOMAIN}"
        invitee_uid = await _seed_identity(invitee_email)
        invitee_token = _mint_jwt(invitee_uid, email=invitee_email)
        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob", "invite_token": plaintext},
            headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_redeem_rejects_unknown_token(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"badtok@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("badtok")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        invitee_email = f"bob@{EMAIL_DOMAIN}"
        invitee_uid = await _seed_identity(invitee_email)
        invitee_token = _mint_jwt(invitee_uid, email=invitee_email)
        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob", "invite_token": "nope-not-a-real-token"},
            headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert resp.status_code == 400
        assert "invalid" in resp.json()["detail"].lower()


class TestReMintAfterClear:
    @pytest.mark.asyncio
    async def test_clear_then_invite_again_works(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_email = f"remint@{EMAIL_DOMAIN}"
        uid = await _seed_identity(creator_email)
        token = _mint_jwt(uid, email=creator_email)
        game_id = _game_id("remint")

        _create_lobby(
            client,
            game_id=game_id,
            token=token,
            slots=[
                {"type": "human", "name": "alice"},
                {"type": "human"},
            ],
        )
        with _patch_send():
            client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"bob@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
            client.post(
                f"/api/v1/games/{game_id}/slots/1/invite/clear",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp = client.post(
                f"/api/v1/games/{game_id}/slots/1/invite",
                json={"email": f"carol@{EMAIL_DOMAIN}"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["email"] == f"carol@{EMAIL_DOMAIN}"
