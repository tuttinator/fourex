"""MCP-only agent runtime. See agent_runtime.py and orchestrator.py."""

from .agent_runtime import MCPAgent, TelemetryConfig, TurnTrace, run_agent_turn
from .mcp_client import InProcessMCPClient, MCPClient, StreamableHTTPMCPClient
from .orchestrator import (
    GameRunResult,
    MCPGameOrchestrator,
    OrchestratedGame,
    create_game,
    run_orchestrated_game,
)
from .planner import plan_actions
from .profiles import (
    AGGRESSIVE,
    BALANCED,
    ECONOMIC,
    EXPLORER,
    PROFILES,
    AgentProfile,
    MemoryKind,
    get_profile,
    list_profiles,
)
from .selfplay import (
    SelfPlayResult,
    TurnActionLog,
    check_state_invariants,
    format_failure_report,
    run_self_play,
)
from .telemetry import (
    CompactionEvent,
    ContextWindowConfig,
    TelemetryRecord,
    TelemetryWriter,
    TurnEntry,
    TurnHistory,
    make_token_counter,
)

__all__ = [
    "AGGRESSIVE",
    "BALANCED",
    "CompactionEvent",
    "ContextWindowConfig",
    "ECONOMIC",
    "EXPLORER",
    "PROFILES",
    "AgentProfile",
    "GameRunResult",
    "InProcessMCPClient",
    "MCPAgent",
    "MCPClient",
    "MCPGameOrchestrator",
    "MemoryKind",
    "OrchestratedGame",
    "SelfPlayResult",
    "StreamableHTTPMCPClient",
    "TelemetryConfig",
    "TelemetryRecord",
    "TelemetryWriter",
    "TurnActionLog",
    "TurnEntry",
    "TurnHistory",
    "TurnTrace",
    "check_state_invariants",
    "create_game",
    "format_failure_report",
    "get_profile",
    "list_profiles",
    "make_token_counter",
    "plan_actions",
    "run_agent_turn",
    "run_orchestrated_game",
    "run_self_play",
]
