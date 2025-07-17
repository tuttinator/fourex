"""
Enhanced logging system for AI agents.
Captures prompts, responses, thinking tokens, and detailed performance metrics.
"""

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import logfire
import orjson
import structlog
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .llm_providers import LLMResponse

# Load environment variables from .env file
load_dotenv()

console = Console()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@dataclass
class TurnLog:
    """Detailed log for a single turn"""

    turn_number: int
    player_id: str
    game_id: str
    timestamp: float
    duration_ms: int
    success: bool
    error_message: str | None = None

    # Game state
    game_state_summary: dict[str, Any] | None = None

    # LLM interaction
    system_prompt: str | None = None
    user_prompt: str | None = None
    llm_response: LLMResponse | None = None
    thinking_tokens: str | None = None

    # Generated plan
    strategic_analysis: str | None = None
    priorities: list[str] | None = None
    actions: list[dict[str, Any]] | None = None

    # Action results
    submitted_actions: list[dict[str, Any]] | None = None
    action_results: list[dict[str, Any]] | None = None

    # Performance metrics
    llm_latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    provider_used: str | None = None
    model_used: str | None = None
    retry_count: int = 0


@dataclass
class GameLog:
    """Complete log for an entire game"""

    game_id: str
    start_time: float
    end_time: float | None = None
    players: list[str] | None = None
    personalities: dict[str, str] | None = None
    max_turns: int | None = None
    final_turn: int | None = None
    winner: str | None = None

    # Configuration
    game_config: dict[str, Any] | None = None
    llm_config: dict[str, Any] | None = None

    # Turn logs
    turn_logs: list[TurnLog] = None

    # Summary statistics
    total_tokens: int | None = None
    total_latency_ms: int | None = None
    average_turn_duration_ms: int | None = None
    error_count: int = 0

    def __post_init__(self):
        if self.turn_logs is None:
            self.turn_logs = []


class EnhancedLogger:
    """Enhanced logging system with rich output and structured storage"""

    def __init__(self, log_dir: str = "logs", enable_console: bool = True):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.enable_console = enable_console
        self.logger = logger.bind(component="enhanced_logger")

        # Current game log
        self.current_game_log: GameLog | None = None

        # Configure Logfire based on environment variables
        logfire_enabled = os.getenv("LOGFIRE_ENABLED", "false").lower() == "true"
        logfire_console = os.getenv("LOGFIRE_CONSOLE_OUTPUT", "false").lower() == "true"

        logfire.configure(
            send_to_logfire=logfire_enabled,
            console=logfire_console,
            token=os.getenv("LOGFIRE_TOKEN") if logfire_enabled else None,
        )

        self.logger.info(
            "Enhanced logger initialized",
            log_dir=str(self.log_dir),
            logfire_enabled=logfire_enabled,
            logfire_console=logfire_console,
        )

    @logfire.instrument("start_game_log")
    def start_game_log(
        self,
        game_id: str,
        players: list[str],
        personalities: dict[str, str],
        config: dict[str, Any],
    ) -> GameLog:
        """Start logging for a new game"""
        self.current_game_log = GameLog(
            game_id=game_id,
            start_time=time.time(),
            players=players,
            personalities=personalities,
            game_config=config,
            turn_logs=[],
        )

        if self.enable_console:
            console.print(f"[green]📋 Started logging game: {game_id}[/green]")

        self.logger.info(
            "Game log started",
            game_id=game_id,
            players=players,
            personalities=personalities,
        )

        return self.current_game_log

    @logfire.instrument("log_turn")
    def log_turn(
        self,
        turn_number: int,
        player_id: str,
        game_id: str,
        success: bool,
        duration_ms: int,
        system_prompt: str,
        user_prompt: str,
        llm_response: LLMResponse,
        strategic_analysis: str,
        priorities: list[str],
        actions: list[dict[str, Any]],
        submitted_actions: list[dict[str, Any]],
        game_state_summary: dict[str, Any] | None = None,
        action_results: list[dict[str, Any]] | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> TurnLog:
        """Log a complete turn with all details"""

        turn_log = TurnLog(
            turn_number=turn_number,
            player_id=player_id,
            game_id=game_id,
            timestamp=time.time(),
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            game_state_summary=game_state_summary,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            llm_response=llm_response,
            thinking_tokens=llm_response.thinking if llm_response else None,
            strategic_analysis=strategic_analysis,
            priorities=priorities,
            actions=actions,
            submitted_actions=submitted_actions,
            action_results=action_results,
            llm_latency_ms=llm_response.latency_ms if llm_response else None,
            tokens_in=llm_response.tokens_in if llm_response else None,
            tokens_out=llm_response.tokens_out if llm_response else None,
            provider_used=llm_response.provider if llm_response else None,
            model_used=llm_response.model if llm_response else None,
            retry_count=retry_count,
        )

        # Add to current game log
        if self.current_game_log:
            self.current_game_log.turn_logs.append(turn_log)

            # Update error count
            if not success:
                self.current_game_log.error_count += 1

        # Console output
        if self.enable_console:
            self._display_turn_summary(turn_log)

        # Structured logging
        self.logger.info(
            "Turn completed",
            turn=turn_number,
            player=player_id,
            success=success,
            duration_ms=duration_ms,
            tokens_in=turn_log.tokens_in,
            tokens_out=turn_log.tokens_out,
            provider=turn_log.provider_used,
            has_thinking=turn_log.thinking_tokens is not None,
            retry_count=retry_count,
        )

        # Save incremental turn log
        self._save_turn_log(turn_log)

        return turn_log

    def _display_turn_summary(self, turn_log: TurnLog):
        """Display a rich console summary of the turn"""
        status = "✅" if turn_log.success else "❌"
        thinking_indicator = "🧠" if turn_log.thinking_tokens else ""

        # Create summary table
        table = Table(
            title=f"{status} Turn {turn_log.turn_number} - {turn_log.player_id} {thinking_indicator}"
        )
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Duration", f"{turn_log.duration_ms}ms")
        table.add_row("Provider", turn_log.provider_used or "Unknown")
        table.add_row("Model", turn_log.model_used or "Unknown")

        if turn_log.tokens_in:
            table.add_row("Tokens In", str(turn_log.tokens_in))
        if turn_log.tokens_out:
            table.add_row("Tokens Out", str(turn_log.tokens_out))
        if turn_log.llm_latency_ms:
            table.add_row("LLM Latency", f"{turn_log.llm_latency_ms}ms")

        table.add_row("Actions", str(len(turn_log.actions or [])))

        if turn_log.retry_count > 0:
            table.add_row("Retries", str(turn_log.retry_count))

        if turn_log.error_message:
            table.add_row(
                "Error",
                turn_log.error_message[:50] + "..."
                if len(turn_log.error_message) > 50
                else turn_log.error_message,
            )

        console.print(table)

        # Show thinking tokens if present
        if turn_log.thinking_tokens and len(turn_log.thinking_tokens) > 0:
            console.print(
                f"[yellow]🧠 Thinking: {turn_log.thinking_tokens[:100]}...[/yellow]"
            )

    @logfire.instrument("finish_game_log")
    def finish_game_log(
        self,
        final_turn: int,
        winner: str | None = None,
        final_results: dict[str, Any] | None = None,
    ) -> GameLog | None:
        """Finish the current game log and save to disk"""
        if not self.current_game_log:
            self.logger.warning("No active game log to finish")
            return None

        self.current_game_log.end_time = time.time()
        self.current_game_log.final_turn = final_turn
        self.current_game_log.winner = winner

        # Calculate summary statistics
        self._calculate_summary_stats()

        # Save complete game log
        log_file = self._save_game_log()

        if self.enable_console:
            self._display_game_summary()
            console.print(f"[blue]💾 Game log saved: {log_file}[/blue]")

        self.logger.info(
            "Game log finished",
            game_id=self.current_game_log.game_id,
            final_turn=final_turn,
            winner=winner,
            total_turns=len(self.current_game_log.turn_logs),
            total_tokens=self.current_game_log.total_tokens,
            error_count=self.current_game_log.error_count,
        )

        game_log = self.current_game_log
        self.current_game_log = None
        return game_log

    def _calculate_summary_stats(self):
        """Calculate summary statistics for the game"""
        if not self.current_game_log or not self.current_game_log.turn_logs:
            return

        turn_logs = self.current_game_log.turn_logs

        # Total tokens
        total_tokens = sum(
            (log.tokens_in or 0) + (log.tokens_out or 0) for log in turn_logs
        )
        self.current_game_log.total_tokens = total_tokens

        # Total latency
        total_latency = sum(log.llm_latency_ms or 0 for log in turn_logs)
        self.current_game_log.total_latency_ms = total_latency

        # Average turn duration
        total_duration = sum(log.duration_ms for log in turn_logs)
        self.current_game_log.average_turn_duration_ms = (
            total_duration // len(turn_logs) if turn_logs else 0
        )

    def _display_game_summary(self):
        """Display a rich summary of the completed game"""
        if not self.current_game_log:
            return

        duration = self.current_game_log.end_time - self.current_game_log.start_time

        console.print("\n" + "=" * 60)
        console.print("[bold green]🎮 GAME SUMMARY[/bold green]")
        console.print("=" * 60)

        # Game info
        table = Table(title="Game Information")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Game ID", self.current_game_log.game_id)
        table.add_row("Duration", f"{duration:.1f}s")
        table.add_row("Total Turns", str(len(self.current_game_log.turn_logs)))
        table.add_row("Winner", self.current_game_log.winner or "None")
        table.add_row("Error Count", str(self.current_game_log.error_count))

        if self.current_game_log.total_tokens:
            table.add_row("Total Tokens", f"{self.current_game_log.total_tokens:,}")
        if self.current_game_log.average_turn_duration_ms:
            table.add_row(
                "Avg Turn Duration",
                f"{self.current_game_log.average_turn_duration_ms}ms",
            )

        console.print(table)

        # Player performance
        if self.current_game_log.players:
            player_table = Table(title="Player Performance")
            player_table.add_column("Player", style="cyan")
            player_table.add_column("Personality", style="blue")
            player_table.add_column("Turns", style="yellow")
            player_table.add_column("Success Rate", style="green")
            player_table.add_column("Avg Tokens", style="magenta")
            player_table.add_column("Thinking Turns", style="purple")

            for player in self.current_game_log.players:
                player_turns = [
                    log
                    for log in self.current_game_log.turn_logs
                    if log.player_id == player
                ]

                if player_turns:
                    success_count = sum(1 for log in player_turns if log.success)
                    success_rate = f"{success_count / len(player_turns) * 100:.1f}%"

                    total_tokens = sum(
                        (log.tokens_in or 0) + (log.tokens_out or 0)
                        for log in player_turns
                    )
                    avg_tokens = (
                        total_tokens // len(player_turns) if player_turns else 0
                    )

                    thinking_count = sum(
                        1 for log in player_turns if log.thinking_tokens
                    )

                    personality = self.current_game_log.personalities.get(
                        player, "Unknown"
                    )

                    player_table.add_row(
                        player,
                        personality,
                        str(len(player_turns)),
                        success_rate,
                        str(avg_tokens),
                        str(thinking_count),
                    )

            console.print(player_table)

    def _save_turn_log(self, turn_log: TurnLog):
        """Save individual turn log to disk"""
        turn_file = (
            self.log_dir
            / f"turn_{turn_log.game_id}_{turn_log.turn_number}_{turn_log.player_id}.json"
        )

        # Convert to dict and handle complex objects
        log_dict = asdict(turn_log)

        # Handle LLMResponse
        if turn_log.llm_response:
            log_dict["llm_response"] = asdict(turn_log.llm_response)

        try:
            with open(turn_file, "wb") as f:
                f.write(orjson.dumps(log_dict, option=orjson.OPT_INDENT_2))
        except Exception as e:
            self.logger.error(
                "Failed to save turn log", error=str(e), turn=turn_log.turn_number
            )

    def _save_game_log(self) -> str:
        """Save complete game log to disk"""
        if not self.current_game_log:
            raise RuntimeError("No active game log to save")

        timestamp = int(time.time())
        log_file = (
            self.log_dir / f"game_log_{self.current_game_log.game_id}_{timestamp}.json"
        )

        # Convert to dict and handle complex objects
        log_dict = asdict(self.current_game_log)

        # Handle nested LLMResponse objects
        for i, turn_log in enumerate(log_dict["turn_logs"]):
            if turn_log.get("llm_response"):
                # Already converted by asdict
                pass

        try:
            with open(log_file, "wb") as f:
                f.write(orjson.dumps(log_dict, option=orjson.OPT_INDENT_2))

            return str(log_file)
        except Exception as e:
            self.logger.error("Failed to save game log", error=str(e))
            raise

    def load_game_log(self, file_path: str) -> GameLog:
        """Load a game log from disk"""
        try:
            with open(file_path, "rb") as f:
                data = orjson.loads(f.read())

            # Reconstruct nested objects
            for turn_data in data.get("turn_logs", []):
                if turn_data.get("llm_response"):
                    turn_data["llm_response"] = LLMResponse(**turn_data["llm_response"])

            return GameLog(**data)
        except Exception as e:
            self.logger.error(
                "Failed to load game log", file_path=file_path, error=str(e)
            )
            raise

    def get_recent_logs(self, limit: int = 10) -> list[str]:
        """Get list of recent game log files"""
        log_files = list(self.log_dir.glob("game_log_*.json"))
        log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return [str(f) for f in log_files[:limit]]

    def analyze_player_performance(
        self, player_id: str, recent_games: int = 5
    ) -> dict[str, Any]:
        """Analyze performance of a specific player across recent games"""
        recent_files = self.get_recent_logs(
            recent_games * 2
        )  # Get more files to find enough with this player

        player_logs = []
        for file_path in recent_files:
            try:
                game_log = self.load_game_log(file_path)
                if player_id in (game_log.players or []):
                    player_turns = [
                        log for log in game_log.turn_logs if log.player_id == player_id
                    ]
                    player_logs.extend(player_turns)

                if (
                    len(player_logs) >= recent_games * 10
                ):  # Rough estimate of turns per game
                    break
            except Exception:
                continue

        if not player_logs:
            return {"error": "No logs found for player"}

        # Calculate statistics
        total_turns = len(player_logs)
        successful_turns = sum(1 for log in player_logs if log.success)
        success_rate = successful_turns / total_turns * 100

        total_tokens = sum(
            (log.tokens_in or 0) + (log.tokens_out or 0) for log in player_logs
        )
        avg_tokens_per_turn = total_tokens / total_turns

        thinking_turns = sum(1 for log in player_logs if log.thinking_tokens)
        thinking_rate = thinking_turns / total_turns * 100

        avg_duration = sum(log.duration_ms for log in player_logs) / total_turns
        avg_llm_latency = (
            sum(log.llm_latency_ms or 0 for log in player_logs) / total_turns
        )

        providers_used = {}
        for log in player_logs:
            if log.provider_used:
                providers_used[log.provider_used] = (
                    providers_used.get(log.provider_used, 0) + 1
                )

        return {
            "player_id": player_id,
            "total_turns_analyzed": total_turns,
            "success_rate": f"{success_rate:.1f}%",
            "avg_tokens_per_turn": f"{avg_tokens_per_turn:.1f}",
            "thinking_rate": f"{thinking_rate:.1f}%",
            "avg_turn_duration_ms": f"{avg_duration:.1f}",
            "avg_llm_latency_ms": f"{avg_llm_latency:.1f}",
            "providers_used": providers_used,
            "recent_errors": [
                log.error_message
                for log in player_logs[-10:]
                if not log.success and log.error_message
            ],
        }


# Global enhanced logger instance
enhanced_logger = EnhancedLogger()
