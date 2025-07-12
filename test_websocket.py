#!/usr/bin/env python3

import asyncio

import websockets


async def test_websocket():
    uri = "ws://localhost:8000/api/v1/events?game_id=test"
    print(f"Connecting to {uri}")

    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket")

            # Listen for messages for 5 seconds
            try:
                while True:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    print(f"Received: {message}")
            except TimeoutError:
                print("No more messages received within timeout")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_websocket())
