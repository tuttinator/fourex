/**
 * Per-game credential storage.
 *
 * When a signed-in user creates or joins a lobby, FastAPI mints a
 * `PlayerApiKey` bound to `(game_id, player_id, user_identity_id)` and
 * returns the plaintext key in the response. The browser keeps the key
 * (and the chosen in-game display name) in `localStorage` keyed by game
 * id, then presents the key as `Authorization: Bearer` on every
 * gameplay/diplomacy request for that game.
 *
 * Storage is namespaced under `parley.` so it doesn't collide with
 * legacy `auth_token` entries from earlier iterations.
 */

const KEY_PREFIX = "parley.gamekey.";
const PID_PREFIX = "parley.playerid.";

export interface GameCredentials {
  apiKey: string;
  playerId: string;
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function setGameCredentials(
  gameId: string,
  creds: GameCredentials,
): void {
  if (!isBrowser()) return;
  localStorage.setItem(`${KEY_PREFIX}${gameId}`, creds.apiKey);
  localStorage.setItem(`${PID_PREFIX}${gameId}`, creds.playerId);
}

export function getGameCredentials(gameId: string): GameCredentials | null {
  if (!isBrowser()) return null;
  const apiKey = localStorage.getItem(`${KEY_PREFIX}${gameId}`);
  const playerId = localStorage.getItem(`${PID_PREFIX}${gameId}`);
  if (!apiKey || !playerId) return null;
  return { apiKey, playerId };
}

export function getGameApiKey(gameId: string): string | null {
  if (!isBrowser()) return null;
  return localStorage.getItem(`${KEY_PREFIX}${gameId}`);
}

export function getGamePlayerId(gameId: string): string | null {
  if (!isBrowser()) return null;
  return localStorage.getItem(`${PID_PREFIX}${gameId}`);
}

export function clearGameCredentials(gameId: string): void {
  if (!isBrowser()) return;
  localStorage.removeItem(`${KEY_PREFIX}${gameId}`);
  localStorage.removeItem(`${PID_PREFIX}${gameId}`);
}
