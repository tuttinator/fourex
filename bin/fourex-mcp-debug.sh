#!/bin/bash
exec 2>/tmp/fourex-mcp-debug.log
echo "=== fourex-mcp-debug ===" >&2
echo "PWD: $(pwd)" >&2
echo "PATH: $PATH" >&2
echo "args: $@" >&2
echo "DATABASE_URL: $DATABASE_URL" >&2
echo "which uv: $(which uv 2>&1)" >&2
echo "Starting server..." >&2
exec uv run --project /Users/caleb/Projects/Mokotahi/fourex fourex-mcp stdio
