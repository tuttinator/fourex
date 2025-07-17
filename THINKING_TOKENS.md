# Thinking Token Extraction Feature

## Overview

The 4X AI agent system now supports extraction and logging of thinking tokens from LLM responses across all providers. This feature captures the model's reasoning process when available, particularly useful for models like Qwen that output `<think>...</think>` tags.

## Implementation

### Core Function
Added `extract_thinking_tokens()` utility function in `agents/src/llm_providers.py`:

```python
def extract_thinking_tokens(content: str) -> tuple[str, str | None]:
    """
    Extract thinking tokens from content if present.

    Looks for <think>...</think> tags and extracts the content inside.
    Returns a tuple of (cleaned_content, thinking_tokens).
    """
```

### Provider Integration
Updated all LLM providers to use the thinking extraction:

- ✅ **OpenAI Provider** - Now extracts thinking tokens
- ✅ **Replicate Provider** - Now extracts thinking tokens
- ✅ **HuggingFace Provider** - Now extracts thinking tokens
- ✅ **LLM Studio Provider** - Updated to use shared function

### Data Flow

1. **LLM Response** → Raw content with optional `<think>...</think>` tags
2. **Extraction** → `extract_thinking_tokens()` separates thinking from main content
3. **LLMResponse** → Stores both cleaned content and thinking tokens
4. **Enhanced Logging** → Saves thinking tokens to turn logs
5. **Console Display** → Shows 🧠 indicator when thinking is present

## Features

### Automatic Detection
- Detects `<think>...</think>` tags in any LLM response
- Safely handles malformed or incomplete tags
- Extracts first thinking block if multiple exist

### Enhanced Logging
- Thinking tokens saved in turn logs (`thinking_tokens` field)
- Console display shows 🧠 indicator for turns with thinking
- Analytics track thinking token usage rates

### Cross-Provider Support
- Works with all LLM providers (OpenAI, Replicate, HuggingFace, LLM Studio)
- Consistent extraction logic regardless of provider
- No provider-specific configuration needed

## Benefits

### Debugging & Analysis
- **Model Reasoning**: See how the AI agent thinks through decisions
- **Strategy Analysis**: Understand strategic reasoning behind actions
- **Error Diagnosis**: Identify where reasoning goes wrong

### Model Comparison
- **Provider Comparison**: Compare thinking quality across providers
- **Model Evaluation**: Assess reasoning capabilities of different models
- **Performance Metrics**: Track thinking token usage and quality

### Development Insights
- **Prompt Engineering**: Improve prompts based on thinking patterns
- **Agent Behavior**: Understand agent decision-making process
- **Game Balance**: Analyze strategic thinking for game tuning

## Usage

### Viewing Thinking Tokens

**In Console Output:**
```
🧠 Thinking: I need to analyze the game state carefully...
```

**In Log Files:**
```json
{
  "thinking_tokens": "I need to analyze the game state carefully. Looking at the current situation: - I have one unit at starting position - Resources are limited...",
  "turn_number": 1,
  "player_id": "Alice"
}
```

### Analytics
- Player performance tables show "Thinking Turns" count
- Turn logs include thinking rate statistics
- Enhanced logging displays thinking indicators

## Testing

The implementation has been tested with:
- ✅ Content with valid thinking tags
- ✅ Content without thinking tags
- ✅ Malformed/incomplete thinking tags
- ✅ Multiple thinking blocks
- ✅ Cross-provider compatibility

## Example

**LLM Output:**
```
<think>
I need to decide between exploring or founding a city.
My scout is at (2,3) and I see a forest tile nearby.
The forest might have wood resources which I need.
I should move there first before deciding on city placement.
</think>

Based on my analysis, I will move my scout to the forest tile to gather intelligence before making strategic decisions.
```

**Extracted:**
- **Thinking**: "I need to decide between exploring or founding a city..."
- **Content**: "Based on my analysis, I will move my scout to the forest tile..."

This feature provides unprecedented insight into AI agent decision-making processes! 🧠✨
