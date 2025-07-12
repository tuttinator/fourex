#!/usr/bin/env python3
"""
Test script for 4X AI agents.
Runs basic tests to verify agent functionality.
"""

import sys
import requests
import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

def test_imports():
    """Test that all required modules can be imported"""
    try:
        from src.agent import FourXAgent, GameClient, LLMClient
        from src.orchestrator import GameOrchestrator, GameConfig
        from src.personalities import list_personalities, get_personality_description
        console.print("[green]✓ All imports successful[/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗ Import failed: {e}[/red]")
        return False

def test_game_backend(url="http://localhost:8000"):
    """Test connection to game backend"""
    try:
        response = requests.get(f"{url}/health", timeout=5)
        if response.status_code == 200:
            console.print(f"[green]✓ Game backend accessible at {url}[/green]")
            return True
        else:
            console.print(f"[yellow]⚠ Game backend returned status {response.status_code}[/yellow]")
            return False
    except Exception as e:
        console.print(f"[red]✗ Game backend not accessible: {e}[/red]")
        return False

def test_llm_backend(url="http://localhost:1234"):
    """Test connection to LLM backend"""
    try:
        response = requests.get(f"{url}/v1/models", timeout=5)
        if response.status_code == 200:
            models = response.json()
            console.print(f"[green]✓ LLM backend accessible at {url}[/green]")
            if "data" in models and models["data"]:
                console.print(f"[green]  Available models: {len(models['data'])}[/green]")
                for model in models["data"][:3]:  # Show first 3 models
                    console.print(f"    - {model.get('id', 'Unknown')}")
            return True
        else:
            console.print(f"[yellow]⚠ LLM backend returned status {response.status_code}[/yellow]")
            return False
    except Exception as e:
        console.print(f"[red]✗ LLM backend not accessible: {e}[/red]")
        return False

def test_llm_completion(url="http://localhost:1234", model="qwen/qwen3-32b"):
    """Test LLM completion"""
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'Hello, World!' and nothing else."}
            ],
            "temperature": 0.1,
            "max_tokens": 50
        }
        
        response = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if "choices" in result and result["choices"]:
                content = result["choices"][0]["message"]["content"]
                console.print(f"[green]✓ LLM completion successful[/green]")
                console.print(f"[blue]  Response: {content.strip()}[/blue]")
                return True
            else:
                console.print(f"[yellow]⚠ LLM response missing choices[/yellow]")
                return False
        else:
            console.print(f"[red]✗ LLM completion failed: {response.status_code}[/red]")
            return False
    except Exception as e:
        console.print(f"[red]✗ LLM completion error: {e}[/red]")
        return False

def test_agent_creation():
    """Test agent creation"""
    try:
        from src.agent import FourXAgent
        agent = FourXAgent("test_player", "balanced")
        console.print("[green]✓ Agent creation successful[/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗ Agent creation failed: {e}[/red]")
        return False

def test_personalities():
    """Test personality system"""
    try:
        from src.personalities import list_personalities, get_personality_description
        personalities = list_personalities()
        console.print(f"[green]✓ Personalities loaded: {len(personalities)}[/green]")
        
        # Test a few personalities
        for personality in personalities[:3]:
            description = get_personality_description(personality)
            console.print(f"  - {personality}: {description[:50]}...")
        
        return True
    except Exception as e:
        console.print(f"[red]✗ Personality system failed: {e}[/red]")
        return False

def test_game_config():
    """Test game configuration"""
    try:
        from src.orchestrator import GameConfig
        config = GameConfig(
            game_id="test_game",
            players=["Alice", "Bob"],
            personalities={"Alice": "aggressive", "Bob": "defensive"},
            max_turns=10
        )
        console.print("[green]✓ Game configuration successful[/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗ Game configuration failed: {e}[/red]")
        return False

def main():
    """Run all tests"""
    console.print(Panel("4X AI Agent Test Suite", style="bold blue"))
    
    tests = [
        ("Imports", test_imports),
        ("Game Backend", test_game_backend),
        ("LLM Backend", test_llm_backend),
        ("LLM Completion", test_llm_completion),
        ("Agent Creation", test_agent_creation),
        ("Personalities", test_personalities),
        ("Game Config", test_game_config)
    ]
    
    results = []
    for test_name, test_func in tests:
        console.print(f"\n[bold]Testing {test_name}...[/bold]")
        result = test_func()
        results.append((test_name, result))
    
    # Summary
    console.print(f"\n{'='*50}")
    console.print("[bold]Test Results Summary[/bold]")
    console.print(f"{'='*50}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[green]PASS[/green]" if result else "[red]FAIL[/red]"
        console.print(f"{test_name:.<30} {status}")
    
    console.print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        console.print("[green]🎉 All tests passed! Ready to run agents.[/green]")
    else:
        console.print("[red]❌ Some tests failed. Check configuration.[/red]")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)