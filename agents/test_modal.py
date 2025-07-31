#!/usr/bin/env python3
"""Test script for Modal Ollama endpoint."""

import os
import sys

import httpx
from dotenv import load_dotenv


def test_modal_endpoint():
    """Test the Modal Ollama endpoint."""
    load_dotenv()

    url = os.getenv("MODAL_OLLAMA_URL")
    if not url:
        print("❌ Error: MODAL_OLLAMA_URL not found in .env")
        sys.exit(1)

    print(f"Testing {url}...")

    try:
        response = httpx.post(
            f"{url}/chat/completions",
            json={
                "model": "qwen3:32b",
                "messages": [
                    {"role": "user", "content": 'Hello! Can you respond with just "Modal Ollama is working!"?'}
                ],
                "max_tokens": 50,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()
        print("✅ Success! Response:", result["choices"][0]["message"]["content"])
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    test_modal_endpoint()
    test_modal_endpoint()
