"""Tests for Phase 8 treaty-lifecycle WebSocket broadcasts.

Covers the backend-visible slice of
``plans/human-frontend-parity.md`` Phase 8:

* ``PROPOSE_TREATY`` emits ``diplomacy.proposal_received`` scoped to
  proposer + recipient only (third players do not see the body).
* ``RESPOND_TO_TREATY`` emits ``diplomacy.proposal_responded`` with the
  ``accepted`` / ``declined`` outcome; on ``accepted`` the newly-ratified
  ``treaty_id`` rides along so the recipient's UI can jump straight to
  the active-treaty entry.
* ``WITHDRAW_TREATY`` emits ``diplomacy.proposal_responded`` with
  ``outcome == "withdrawn"``.
* ``CANCEL_TREATY`` emits ``diplomacy.treaty_cancelled`` scoped to the
  two parties with the appropriate ``cause``.
* No lifecycle events fire on a turn without treaty actions.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.api.persistent_game_controller import (
    get_persistent_game_controller,
)
from backend.src.api.websocket import manager
from backend.src.auth import create_player_key
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerAction,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
)
from backend.src.database.repository import GameRepository
from backend.src.game.models import (
    CancelTreatyAction,
    FreeTextClause,
    GameState,
    ProposeTreatyAction,
    RespondToTreatyAction,
    WithdrawTreatyAction,
)
from backend.src.game.rules import record_discovery
from backend.src.main import app

_GAME_PREFIX = "phase8"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _clean_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        for table in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
        ):
            await session.execute(
                delete(table).where(table.game_id.like(f"{_GAME_PREFIX}_%"))
            )
        await session.execute(delete(Game).where(Game.id.like(f"{_GAME_PREFIX}_%")))
        await session.commit()
    manager._by_game.clear()
    yield
    async with async_session_factory() as session:
        for table in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
        ):
            await session.execute(
                delete(table).where(table.game_id.like(f"{_GAME_PREFIX}_%"))
            )
        await session.execute(delete(Game).where(Game.id.like(f"{_GAME_PREFIX}_%")))
        await session.commit()
    manager._by_game.clear()


def _game_id(suffix: str) -> str:
    return f"{_GAME_PREFIX}_{suffix}_{int(time.time() * 1000000)}"


async def _mint_key(game_id: str, player_id: str) -> str:
    async with async_session_factory() as session:
        key = await create_player_key(session, game_id, player_id)
        await session.commit()
        return key


def _start_game(client: TestClient, game_id: str, players: list[str]) -> None:
    resp = client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": players, "seed": 42},
    )
    assert resp.status_code == 200


async def _seed_discovery(game_id: str, pairs: list[tuple[str, str]]) -> None:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        game = await repo.get_game(game_id)
        assert game is not None
        state = GameState.model_validate(game.state)
        for viewer, target in pairs:
            record_discovery(state, viewer, target)
        await repo.update_game_state(game_id, state)
        await session.commit()


def _collect_until_resolved(ws, limit: int = 30) -> list[dict]:
    seen: list[dict] = []
    for _ in range(limit):
        frame = ws.receive_json()
        seen.append(frame)
        if frame["type"] == "turn.resolved":
            return seen
    raise AssertionError(
        f"turn.resolved not seen in {limit} frames; saw {[f['type'] for f in seen]}"
    )


def _drain_remaining(ws, limit: int = 20) -> list[dict]:
    """Drain any diplomacy-* frames queued after ``turn.resolved``."""
    frames: list[dict] = []
    for _ in range(limit):
        try:
            frames.append(ws.receive_json())
        except Exception:  # noqa: BLE001 — receive_json raises on empty
            break
    return frames


async def _submit(game_id: str, player_id: str, actions: list) -> None:
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        await controller.submit_player_actions(game_id, player_id, actions)
        await session.commit()


class TestProposalReceivedBroadcast:
    @pytest.mark.asyncio
    async def test_emitted_to_proposer_and_recipient(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("proposed")
        _start_game(client, game_id, ["alice", "bob"])
        await _seed_discovery(game_id, [("alice", "bob"), ("bob", "alice")])

        alice_key = await _mint_key(game_id, "alice")
        bob_key = await _mint_key(game_id, "bob")

        with (
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
            ) as alice_ws,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={bob_key}"
            ) as bob_ws,
        ):
            alice_ws.receive_json()
            bob_ws.receive_json()

            await _submit(
                game_id,
                "alice",
                [
                    ProposeTreatyAction(
                        recipient="bob",
                        clauses=[FreeTextClause(text="friendship")],
                    )
                ],
            )
            await _submit(game_id, "bob", [])

            _collect_until_resolved(alice_ws)
            _collect_until_resolved(bob_ws)

            alice_msg = alice_ws.receive_json()
            bob_msg = bob_ws.receive_json()

            for frame, perspective in ((alice_msg, "alice"), (bob_msg, "bob")):
                assert frame["type"] == "diplomacy.proposal_received", perspective
                assert frame["game_id"] == game_id, perspective
                proposal = frame["proposal"]
                assert proposal["proposer"] == "alice", perspective
                assert proposal["recipient"] == "bob", perspective
                assert proposal["clauses"][0]["clause_type"] == "free_text", perspective
                assert proposal["clauses"][0]["text"] == "friendship", perspective
                assert isinstance(proposal["id"], int), perspective

    @pytest.mark.asyncio
    async def test_third_party_does_not_receive_proposal(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("scoped_prop")
        _start_game(client, game_id, ["alice", "bob", "carol"])
        await _seed_discovery(
            game_id,
            [
                ("alice", "bob"),
                ("bob", "alice"),
                ("alice", "carol"),
                ("carol", "alice"),
                ("bob", "carol"),
                ("carol", "bob"),
            ],
        )

        alice_key = await _mint_key(game_id, "alice")
        carol_key = await _mint_key(game_id, "carol")

        with (
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
            ) as alice_ws,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={carol_key}"
            ) as carol_ws,
        ):
            alice_ws.receive_json()
            carol_ws.receive_json()

            await _submit(
                game_id,
                "alice",
                [
                    ProposeTreatyAction(
                        recipient="bob",
                        clauses=[FreeTextClause(text="secret pact")],
                    )
                ],
            )
            await _submit(game_id, "bob", [])
            await _submit(game_id, "carol", [])

            carol_frames = _collect_until_resolved(carol_ws)
            _collect_until_resolved(alice_ws)

            alice_next = alice_ws.receive_json()
            assert alice_next["type"] == "diplomacy.proposal_received"

            for frame in carol_frames:
                assert frame["type"] != "diplomacy.proposal_received", (
                    f"carol leaked: {frame}"
                )


class TestProposalRespondedBroadcast:
    @pytest.mark.asyncio
    async def test_accepted_carries_treaty_id(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("accepted")
        _start_game(client, game_id, ["alice", "bob"])
        await _seed_discovery(game_id, [("alice", "bob"), ("bob", "alice")])

        alice_key = await _mint_key(game_id, "alice")
        bob_key = await _mint_key(game_id, "bob")

        # Turn 0: alice proposes.
        await _submit(
            game_id,
            "alice",
            [
                ProposeTreatyAction(
                    recipient="bob",
                    clauses=[FreeTextClause(text="trade route")],
                )
            ],
        )
        await _submit(game_id, "bob", [])

        # Fetch the minted proposal_id.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            state = GameState.model_validate(game.state)
            assert state.pending_proposals, "proposal should be pending after turn 0"
            proposal_id = state.pending_proposals[0].id

        with (
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
            ) as alice_ws,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={bob_key}"
            ) as bob_ws,
        ):
            alice_ws.receive_json()
            bob_ws.receive_json()

            # Turn 1: bob accepts.
            await _submit(game_id, "alice", [])
            await _submit(
                game_id,
                "bob",
                [RespondToTreatyAction(proposal_id=proposal_id, accept=True)],
            )

            _collect_until_resolved(alice_ws)
            _collect_until_resolved(bob_ws)

            alice_evt = alice_ws.receive_json()
            bob_evt = bob_ws.receive_json()

            for frame, perspective in ((alice_evt, "alice"), (bob_evt, "bob")):
                assert frame["type"] == "diplomacy.proposal_responded", perspective
                assert frame["proposal_id"] == proposal_id, perspective
                assert frame["proposer"] == "alice", perspective
                assert frame["recipient"] == "bob", perspective
                assert frame["outcome"] == "accepted", perspective
                assert isinstance(frame["treaty_id"], int), perspective

    @pytest.mark.asyncio
    async def test_declined_outcome(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("declined")
        _start_game(client, game_id, ["alice", "bob"])
        await _seed_discovery(game_id, [("alice", "bob"), ("bob", "alice")])

        alice_key = await _mint_key(game_id, "alice")

        await _submit(
            game_id,
            "alice",
            [
                ProposeTreatyAction(
                    recipient="bob",
                    clauses=[FreeTextClause(text="offer")],
                )
            ],
        )
        await _submit(game_id, "bob", [])

        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            state = GameState.model_validate(game.state)
            proposal_id = state.pending_proposals[0].id

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as alice_ws:
            alice_ws.receive_json()

            await _submit(game_id, "alice", [])
            await _submit(
                game_id,
                "bob",
                [RespondToTreatyAction(proposal_id=proposal_id, accept=False)],
            )

            _collect_until_resolved(alice_ws)
            evt = alice_ws.receive_json()
            assert evt["type"] == "diplomacy.proposal_responded"
            assert evt["outcome"] == "declined"
            assert evt["treaty_id"] is None

    @pytest.mark.asyncio
    async def test_withdrawn_outcome(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("withdrawn")
        _start_game(client, game_id, ["alice", "bob"])
        await _seed_discovery(game_id, [("alice", "bob"), ("bob", "alice")])

        bob_key = await _mint_key(game_id, "bob")

        await _submit(
            game_id,
            "alice",
            [
                ProposeTreatyAction(
                    recipient="bob",
                    clauses=[FreeTextClause(text="maybe")],
                )
            ],
        )
        await _submit(game_id, "bob", [])

        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            state = GameState.model_validate(game.state)
            proposal_id = state.pending_proposals[0].id

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={bob_key}"
        ) as bob_ws:
            bob_ws.receive_json()

            await _submit(
                game_id,
                "alice",
                [WithdrawTreatyAction(proposal_id=proposal_id)],
            )
            await _submit(game_id, "bob", [])

            _collect_until_resolved(bob_ws)
            evt = bob_ws.receive_json()
            assert evt["type"] == "diplomacy.proposal_responded"
            assert evt["outcome"] == "withdrawn"
            assert evt["proposal_id"] == proposal_id


class TestTreatyCancelledBroadcast:
    @pytest.mark.asyncio
    async def test_cancel_scoped_to_parties(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("cancelled")
        _start_game(client, game_id, ["alice", "bob", "carol"])
        await _seed_discovery(
            game_id,
            [
                ("alice", "bob"),
                ("bob", "alice"),
                ("alice", "carol"),
                ("carol", "alice"),
                ("bob", "carol"),
                ("carol", "bob"),
            ],
        )

        # Turn 0: alice proposes free-text treaty to bob.
        await _submit(
            game_id,
            "alice",
            [
                ProposeTreatyAction(
                    recipient="bob",
                    clauses=[FreeTextClause(text="informational")],
                )
            ],
        )
        await _submit(game_id, "bob", [])
        await _submit(game_id, "carol", [])

        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            state = GameState.model_validate(game.state)
            proposal_id = state.pending_proposals[0].id

        # Turn 1: bob accepts -> treaty ratified.
        await _submit(game_id, "alice", [])
        await _submit(
            game_id,
            "bob",
            [RespondToTreatyAction(proposal_id=proposal_id, accept=True)],
        )
        await _submit(game_id, "carol", [])

        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            state = GameState.model_validate(game.state)
            assert state.active_treaties, "treaty should be active after acceptance"
            treaty_id = state.active_treaties[0].id

        alice_key = await _mint_key(game_id, "alice")
        bob_key = await _mint_key(game_id, "bob")
        carol_key = await _mint_key(game_id, "carol")

        with (
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
            ) as alice_ws,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={bob_key}"
            ) as bob_ws,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={carol_key}"
            ) as carol_ws,
        ):
            alice_ws.receive_json()
            bob_ws.receive_json()
            carol_ws.receive_json()

            # Turn 2: alice cancels.
            await _submit(
                game_id,
                "alice",
                [CancelTreatyAction(treaty_id=treaty_id)],
            )
            await _submit(game_id, "bob", [])
            await _submit(game_id, "carol", [])

            carol_frames = _collect_until_resolved(carol_ws)
            _collect_until_resolved(alice_ws)
            _collect_until_resolved(bob_ws)

            alice_evt = alice_ws.receive_json()
            bob_evt = bob_ws.receive_json()

            for frame, perspective in ((alice_evt, "alice"), (bob_evt, "bob")):
                assert frame["type"] == "diplomacy.treaty_cancelled", perspective
                assert frame["treaty_id"] == treaty_id, perspective
                assert set(frame["parties"]) == {"alice", "bob"}, perspective
                assert frame["cause"] in {"cancelled", "violated"}, perspective

            for frame in carol_frames:
                assert frame["type"] != "diplomacy.treaty_cancelled", (
                    f"carol leaked: {frame}"
                )


class TestNoLifecycleEventOnQuietTurn:
    @pytest.mark.asyncio
    async def test_no_events_when_no_treaty_actions(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("quiet")
        _start_game(client, game_id, ["alice", "bob"])

        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as alice_ws:
            alice_ws.receive_json()

            await _submit(game_id, "alice", [])
            await _submit(game_id, "bob", [])

            frames = _collect_until_resolved(alice_ws)
            for frame in frames:
                assert frame["type"] not in {
                    "diplomacy.proposal_received",
                    "diplomacy.proposal_responded",
                    "diplomacy.treaty_cancelled",
                }, f"unexpected lifecycle event: {frame}"
