#!/usr/bin/env python3
"""
Simple test for MCP calculate_distances functionality
"""

import asyncio
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from .src.mcp_server import MCPGameServer


async def test_calculate_distances():
    """Test the calculate_distances function directly"""

    print("Testing MCP calculate_distances function...")

    # Create server directly
    server = MCPGameServer()

    # Test valid call
    print("\n1. Testing valid call:")
    try:
        args = {
            "from_locations": [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
            "to_locations": [{"x": 5, "y": 6}, {"x": 7, "y": 8}],
        }
        print(f"Args: {args}")
        result = await server._calculate_distances(args)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")

    # Test invalid call (missing parameters)
    print("\n2. Testing invalid call (missing from_locations):")
    try:
        args = {"to_locations": [{"x": 5, "y": 6}]}
        print(f"Args: {args}")
        result = await server._calculate_distances(args)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")

    # Test call_tool method
    print("\n3. Testing via call_tool method:")
    try:
        args = {
            "from_locations": [{"x": 1, "y": 2}],
            "to_locations": [{"x": 5, "y": 6}],
        }
        print(f"Args: {args}")
        result = await server.call_tool("calculate_distances", args)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_calculate_distances())
