"""Helpers for the ``lobby_slots`` JSON column on ``Game``.

Phase 2 of the lobby + skill split introduces the column without
changing any user-visible behaviour: every slot is still Human and
the create dialog is unchanged. Future phases extend the structure
with Agent slots, reservations, and per-slot keys.

The shape stored on disk is intentionally a list of plain dicts (not
Pydantic models) so a new optional field can be added without
running a data migration — the controller upserts the dict in place
and any consumer that doesn't know about the field simply ignores
it. Conversely, every reader normalises through
``coerce_slots`` / ``derive_slots_from_players`` so legacy rows
(``lobby_slots IS NULL``) and partial entries always materialise as
a fully-populated list of slot dicts.
"""

from __future__ import annotations

from typing import Any

SlotDict = dict[str, Any]

# Canonical keys for a slot record on disk and on the wire. Listed
# explicitly so callers can iterate without leaking extra keys that
# might be added by mistake. ``plaintext_key`` is the Phase 3
# transient field — populated for Agent slots while ``status ==
# "waiting"`` so the lobby UI can render a copy-button affordance, and
# stripped on game start so the lobby never doubles as a long-lived
# secret store.
SLOT_KEYS = (
    "slot_index",
    "type",
    "name",
    "reserved_email",
    "player_api_key_id",
    "plaintext_key",
)


def make_human_slot(
    slot_index: int,
    *,
    name: str | None = None,
    player_api_key_id: int | None = None,
    reserved_email: str | None = None,
) -> SlotDict:
    """Build a Human slot dict with the canonical key order.

    All Phase 2 callers create Human slots; the Agent path lands in
    Phase 3.
    """
    return {
        "slot_index": slot_index,
        "type": "human",
        "name": name,
        "reserved_email": reserved_email,
        "player_api_key_id": player_api_key_id,
        "plaintext_key": None,
    }


def make_agent_slot(
    slot_index: int,
    *,
    name: str,
    player_api_key_id: int | None = None,
    plaintext_key: str | None = None,
) -> SlotDict:
    """Build an Agent slot dict.

    Agent slots are bound to a specific display name at create time and
    carry the freshly minted API key as ``plaintext_key`` so the creator
    can copy it out of the lobby UI. The plaintext lives only while the
    game is in ``waiting`` — see ``strip_plaintext_keys``.
    """
    return {
        "slot_index": slot_index,
        "type": "agent",
        "name": name,
        "reserved_email": None,
        "player_api_key_id": player_api_key_id,
        "plaintext_key": plaintext_key,
    }


def derive_slots_from_players(players: list[str], player_slots: int) -> list[SlotDict]:
    """Synthesise an all-Human ``lobby_slots`` array from a roster.

    Used as the legacy fallback when a row predates the column. The
    first ``len(players)`` slots are filled with the existing player
    ids (without a ``player_api_key_id`` — Phase 3 starts wiring that
    explicitly); the remainder are empty Human slots.
    """
    slots: list[SlotDict] = []
    for i in range(player_slots):
        if i < len(players):
            slots.append(make_human_slot(i, name=players[i]))
        else:
            slots.append(make_human_slot(i))
    return slots


def coerce_slots(raw: Any, players: list[str], player_slots: int) -> list[SlotDict]:
    """Normalise the persisted ``lobby_slots`` value into a slot list.

    ``None`` (legacy rows) falls back to
    ``derive_slots_from_players``. Otherwise each entry is filled in
    with default keys so consumers can rely on the full shape.
    """
    if raw is None:
        return derive_slots_from_players(players, player_slots)
    if not isinstance(raw, list):
        return derive_slots_from_players(players, player_slots)
    coerced: list[SlotDict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        slot_index = entry.get("slot_index")
        if not isinstance(slot_index, int):
            continue
        coerced.append(
            {
                "slot_index": slot_index,
                "type": entry.get("type", "human") or "human",
                "name": entry.get("name"),
                "reserved_email": entry.get("reserved_email"),
                "player_api_key_id": entry.get("player_api_key_id"),
                "plaintext_key": entry.get("plaintext_key"),
            }
        )
    coerced.sort(key=lambda s: s["slot_index"])
    return coerced


def strip_plaintext_keys(slots: list[SlotDict]) -> list[SlotDict]:
    """Return a new slot list with every ``plaintext_key`` cleared.

    Called when the game flips from ``waiting`` to ``active`` so the
    lobby endpoint stops doubling as a secret store. Pure — does not
    mutate the input.
    """
    return [{**slot, "plaintext_key": None} for slot in slots]


def redact_plaintext_keys(slots: list[SlotDict]) -> list[SlotDict]:
    """Return a slot list with ``plaintext_key`` removed from the wire.

    Used by ``GET /games/{id}`` for any caller that isn't the creator
    or for any game past ``waiting`` — the field is dropped entirely
    rather than nulled so non-creator callers can't even infer the
    presence of a key.
    """
    return [{**slot, "plaintext_key": None} for slot in slots]


def fill_slot(
    slots: list[SlotDict],
    slot_index: int,
    *,
    name: str | None,
    player_api_key_id: int | None,
) -> list[SlotDict]:
    """Return a new slot list with ``slot_index`` filled to ``name``.

    Pure — does not mutate the input. Used by create/join to seat a
    player in a specific slot. Slots outside ``slot_index`` are left
    untouched.
    """
    updated: list[SlotDict] = []
    for slot in slots:
        if slot["slot_index"] == slot_index:
            updated.append(
                {**slot, "name": name, "player_api_key_id": player_api_key_id}
            )
        else:
            updated.append(dict(slot))
    return updated


def clear_slot_by_name(slots: list[SlotDict], name: str) -> list[SlotDict]:
    """Return a new slot list with the slot named ``name`` cleared.

    Clears ``name`` and ``player_api_key_id``; the slot index and
    type are preserved so the seat can be re-filled later. If no
    slot matches the name, the list is returned unchanged.
    """
    updated: list[SlotDict] = []
    for slot in slots:
        if slot.get("name") == name:
            updated.append({**slot, "name": None, "player_api_key_id": None})
        else:
            updated.append(dict(slot))
    return updated


def first_empty_slot_index(slots: list[SlotDict]) -> int | None:
    """Return the index of the first unfilled, unreserved Human slot.

    Phase 5 changes the contract: a slot with ``reserved_email`` set is
    locked to the invitee (and only joinable through the token-redemption
    path), so an open join must skip it. Open Human slots — no name and
    no reservation — remain first-come-first-served.
    """
    for slot in slots:
        if (
            slot.get("type") == "human"
            and slot.get("name") is None
            and not slot.get("reserved_email")
        ):
            return slot["slot_index"]
    return None


def find_slot_by_index(slots: list[SlotDict], slot_index: int) -> SlotDict | None:
    """Return the slot record at ``slot_index``, or ``None`` if missing."""
    for slot in slots:
        if slot.get("slot_index") == slot_index:
            return slot
    return None
