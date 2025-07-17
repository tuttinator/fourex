"""
Multi-LLM provider support for AI agents.
Supports OpenAI, Replicate, Baseten, HuggingFace, and local LLM Studio.
"""

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
import instructor
import logfire
import orjson
import structlog
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Load environment variables
load_dotenv()

# Configure Logfire based on environment variables
logfire_enabled = os.getenv("LOGFIRE_ENABLED", "false").lower() == "true"
logfire_console = os.getenv("LOGFIRE_CONSOLE_OUTPUT", "false").lower() == "true"

logfire.configure(
    send_to_logfire=logfire_enabled,
    console=logfire_console,
    token=os.getenv("LOGFIRE_TOKEN") if logfire_enabled else None,
)


def extract_thinking_tokens(content: str) -> tuple[str, str | None]:
    """
    Extract thinking tokens from content if present.

    Looks for <think>...</think> tags and extracts the content inside.
    Returns a tuple of (cleaned_content, thinking_tokens).

    Args:
        content: The raw content from the LLM response

    Returns:
        tuple: (content_without_thinking, thinking_tokens_or_none)
    """
    if not content or "<think>" not in content or "</think>" not in content:
        return content, None

    think_start = content.find("<think>") + 7
    think_end = content.find("</think>")

    if think_start >= think_end or think_start < 7:
        return content, None

    # Extract thinking content
    thinking_tokens = content[think_start:think_end].strip()

    # Remove thinking tags and content from main response
    cleaned_content = (
        content[: content.find("<think>")] + content[content.find("</think>") + 8 :]
    ).strip()

    return cleaned_content, thinking_tokens


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
class LLMResponse:
    """Standardized LLM response with metadata"""

    content: str
    thinking: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    model: str | None = None
    provider: str | None = None
    raw_response: dict[str, Any] | None = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""

    def __init__(self, model: str, **kwargs):
        self.model = model
        self.provider_name = self.__class__.__name__.lower().replace("provider", "")
        self.logger = logger.bind(provider=self.provider_name, model=model)

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        response_model: BaseModel | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from the LLM"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available and configured"""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI API provider"""

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None, **kwargs):
        super().__init__(model, **kwargs)
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.instructor_client = instructor.from_openai(self.client)

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, Exception)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    @logfire.instrument("openai_generate", extract_args=True)
    async def generate(
        self,
        messages: list[dict[str, str]],
        response_model: BaseModel | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate response using OpenAI API"""
        start_time = time.time()

        try:
            if response_model:
                response = self.instructor_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_model=response_model,
                    **kwargs,
                )
                content = (
                    response.model_dump_json()
                    if hasattr(response, "model_dump_json")
                    else str(response)
                )
                tokens_in = None
                tokens_out = None
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **kwargs,
                )
                content = response.choices[0].message.content
                tokens_in = response.usage.prompt_tokens if response.usage else None
                tokens_out = (
                    response.usage.completion_tokens if response.usage else None
                )

            # Extract thinking tokens from content
            cleaned_content, thinking_tokens = extract_thinking_tokens(content or "")
            content = cleaned_content

            latency_ms = int((time.time() - start_time) * 1000)

            self.logger.info(
                "OpenAI generation completed",
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                has_thinking=thinking_tokens is not None,
            )

            return LLMResponse(
                content=content,
                thinking=thinking_tokens,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                model=self.model,
                provider="openai",
                raw_response=response.model_dump()
                if hasattr(response, "model_dump")
                else None,
            )

        except Exception as e:
            self.logger.error("OpenAI generation failed", error=str(e))
            logfire.log_exception("OpenAI generation error")
            raise

    def is_available(self) -> bool:
        """Check if OpenAI is available"""
        return bool(os.getenv("OPENAI_API_KEY"))


class ReplicateProvider(LLMProvider):
    """Replicate API provider"""

    def __init__(self, model: str, api_token: str | None = None, **kwargs):
        super().__init__(model, **kwargs)
        self.api_token = api_token or os.getenv("REPLICATE_API_TOKEN")

        if self.is_available():
            import replicate

            self.client = replicate.Client(api_token=self.api_token)

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, Exception)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    @logfire.instrument("replicate_generate", extract_args=True)
    async def generate(
        self,
        messages: list[dict[str, str]],
        response_model: BaseModel | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate response using Replicate API"""
        if not self.is_available():
            raise RuntimeError("Replicate API token not configured")

        start_time = time.time()

        try:
            # Convert messages to prompt format
            prompt = self._messages_to_prompt(messages)

            # Run the model
            output = self.client.run(self.model, input={"prompt": prompt, **kwargs})

            # Handle different output formats
            if isinstance(output, list):
                content = "".join(output)
            elif isinstance(output, str):
                content = output
            else:
                content = str(output)

            # Extract thinking tokens from content
            cleaned_content, thinking_tokens = extract_thinking_tokens(content)
            content = cleaned_content

            latency_ms = int((time.time() - start_time) * 1000)

            # Parse structured output if requested
            if response_model:
                try:
                    parsed = orjson.loads(content)
                    content = response_model(**parsed).model_dump_json()
                except Exception as e:
                    self.logger.warning(
                        "Failed to parse structured output", error=str(e)
                    )

            self.logger.info(
                "Replicate generation completed",
                latency_ms=latency_ms,
                has_thinking=thinking_tokens is not None,
            )

            return LLMResponse(
                content=content,
                thinking=thinking_tokens,
                latency_ms=latency_ms,
                model=self.model,
                provider="replicate",
                raw_response={"output": output},
            )

        except Exception as e:
            self.logger.error("Replicate generation failed", error=str(e))
            logfire.log_exception("Replicate generation error")
            raise

    def _messages_to_prompt(self, messages: list[dict[str, str]]) -> str:
        """Convert chat messages to a single prompt"""
        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"Human: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")

        prompt_parts.append("Assistant:")
        return "\n\n".join(prompt_parts)

    def is_available(self) -> bool:
        """Check if Replicate is available"""
        return bool(self.api_token)


class HuggingFaceProvider(LLMProvider):
    """HuggingFace API provider"""

    def __init__(self, model: str, api_token: str | None = None, **kwargs):
        super().__init__(model, **kwargs)
        self.api_token = api_token or os.getenv("HF_TOKEN")
        self.base_url = f"https://api-inference.huggingface.co/models/{model}"

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, Exception)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    @logfire.instrument("huggingface_generate", extract_args=True)
    async def generate(
        self,
        messages: list[dict[str, str]],
        response_model: BaseModel | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate response using HuggingFace API"""
        if not self.is_available():
            raise RuntimeError("HuggingFace API token not configured")

        start_time = time.time()

        try:
            # Convert messages to prompt
            prompt = self._messages_to_prompt(messages)

            headers = {"Authorization": f"Bearer {self.api_token}"}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    json={
                        "inputs": prompt,
                        "parameters": {
                            "max_new_tokens": kwargs.get("max_tokens", 2000),
                            "temperature": kwargs.get("temperature", 0.7),
                            "return_full_text": False,
                        },
                    },
                    timeout=60.0,
                )
                response.raise_for_status()

                result = response.json()

                if isinstance(result, list) and len(result) > 0:
                    content = result[0].get("generated_text", "")
                else:
                    content = str(result)

            # Extract thinking tokens from content
            cleaned_content, thinking_tokens = extract_thinking_tokens(content)
            content = cleaned_content

            latency_ms = int((time.time() - start_time) * 1000)

            # Parse structured output if requested
            if response_model:
                try:
                    parsed = orjson.loads(content)
                    content = response_model(**parsed).model_dump_json()
                except Exception as e:
                    self.logger.warning(
                        "Failed to parse structured output", error=str(e)
                    )

            self.logger.info(
                "HuggingFace generation completed",
                latency_ms=latency_ms,
                has_thinking=thinking_tokens is not None,
            )

            return LLMResponse(
                content=content,
                thinking=thinking_tokens,
                latency_ms=latency_ms,
                model=self.model,
                provider="huggingface",
                raw_response=result,
            )

        except Exception as e:
            self.logger.error("HuggingFace generation failed", error=str(e))
            logfire.log_exception("HuggingFace generation error")
            raise

    def _messages_to_prompt(self, messages: list[dict[str, str]]) -> str:
        """Convert chat messages to a single prompt"""
        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                prompt_parts.append(f"<|system|>\n{content}")
            elif role == "user":
                prompt_parts.append(f"<|user|>\n{content}")
            elif role == "assistant":
                prompt_parts.append(f"<|assistant|>\n{content}")

        prompt_parts.append("<|assistant|>")
        return "\n".join(prompt_parts)

    def is_available(self) -> bool:
        """Check if HuggingFace is available"""
        return bool(self.api_token)


class LLMStudioProvider(LLMProvider):
    """Local LLM Studio provider with thinking tokens support"""

    def __init__(
        self,
        model: str = "qwen/qwen3-32b",
        base_url: str = "http://localhost:1234/v1",
        **kwargs,
    ):
        super().__init__(model, **kwargs)
        self.base_url = base_url
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
        self.instructor_client = instructor.from_openai(
            self.client, mode=instructor.Mode.MD_JSON
        )

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, Exception)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
    )
    @logfire.instrument("llm_studio_generate", extract_args=True)
    async def generate(
        self,
        messages: list[dict[str, str]],
        response_model: BaseModel | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate response using LLM Studio"""
        start_time = time.time()

        try:
            if response_model:
                response = self.instructor_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_model=response_model,
                    **kwargs,
                )
                content = (
                    response.model_dump_json()
                    if hasattr(response, "model_dump_json")
                    else str(response)
                )
                tokens_in = None
                tokens_out = None
                thinking = None
                raw_response = (
                    response.model_dump() if hasattr(response, "model_dump") else None
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **kwargs,
                )

                message = response.choices[0].message
                content = message.content
                tokens_in = response.usage.prompt_tokens if response.usage else None
                tokens_out = (
                    response.usage.completion_tokens if response.usage else None
                )

                # Extract thinking tokens using the utility function
                cleaned_content, thinking = extract_thinking_tokens(content or "")
                content = cleaned_content

                raw_response = (
                    response.model_dump() if hasattr(response, "model_dump") else None
                )

            latency_ms = int((time.time() - start_time) * 1000)

            self.logger.info(
                "LLM Studio generation completed",
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                has_thinking=thinking is not None,
            )

            return LLMResponse(
                content=content,
                thinking=thinking,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                model=self.model,
                provider="llm_studio",
                raw_response=raw_response,
            )

        except Exception as e:
            self.logger.error("LLM Studio generation failed", error=str(e))
            logfire.log_exception("LLM Studio generation error")
            raise

    async def is_available_async(self) -> bool:
        """Check if LLM Studio is available (async)"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/models", timeout=5.0)
                return response.status_code == 200
        except Exception:
            return False

    def is_available(self) -> bool:
        """Check if LLM Studio is available (sync)"""
        try:
            import requests

            response = requests.get(f"{self.base_url}/models", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False


class MultiLLMClient:
    """Client that can switch between multiple LLM providers"""

    def __init__(
        self,
        primary_provider: str = "llm_studio",
        fallback_providers: list[str] | None = None,
    ):
        self.providers: dict[str, LLMProvider] = {}
        self.primary_provider = primary_provider
        self.fallback_providers = fallback_providers or ["openai"]
        self.logger = logger.bind(component="multi_llm_client")

        # Initialize providers
        self._setup_providers()

    def _setup_providers(self):
        """Setup all available providers"""
        # LLM Studio
        self.providers["llm_studio"] = LLMStudioProvider()

        # OpenAI
        if os.getenv("OPENAI_API_KEY"):
            self.providers["openai"] = OpenAIProvider()

        # Replicate
        if os.getenv("REPLICATE_API_TOKEN"):
            try:
                self.providers["replicate"] = ReplicateProvider("meta/llama-2-70b-chat")
            except ImportError:
                self.logger.warning("Replicate package not available")

        # HuggingFace
        if os.getenv("HF_TOKEN"):
            self.providers["huggingface"] = HuggingFaceProvider(
                "microsoft/DialoGPT-large"
            )

        self.logger.info("Initialized providers", available=list(self.providers.keys()))

    def add_provider(self, name: str, provider: LLMProvider):
        """Add a custom provider"""
        self.providers[name] = provider
        self.logger.info("Added custom provider", name=name)

    @logfire.instrument("multi_llm_generate", extract_args=True)
    async def generate(
        self,
        messages: list[dict[str, str]],
        response_model: BaseModel | None = None,
        provider_override: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate response using primary provider with fallbacks"""

        # Determine provider order
        provider_order = []
        if provider_override and provider_override in self.providers:
            provider_order.append(provider_override)
        else:
            if self.primary_provider in self.providers:
                provider_order.append(self.primary_provider)
            provider_order.extend(
                [p for p in self.fallback_providers if p in self.providers]
            )

        # Remove duplicates while preserving order
        provider_order = list(dict.fromkeys(provider_order))

        last_error = None

        for provider_name in provider_order:
            provider = self.providers[provider_name]

            try:
                self.logger.info("Attempting generation", provider=provider_name)

                # Check availability
                if not provider.is_available():
                    self.logger.warning(
                        "Provider not available", provider=provider_name
                    )
                    continue

                response = await provider.generate(messages, response_model, **kwargs)

                self.logger.info(
                    "Generation successful",
                    provider=provider_name,
                    latency_ms=response.latency_ms,
                )

                return response

            except Exception as e:
                last_error = e
                self.logger.warning(
                    "Provider failed, trying next",
                    provider=provider_name,
                    error=str(e),
                )
                continue

        # All providers failed
        error_msg = f"All LLM providers failed. Last error: {last_error}"
        self.logger.error("All providers failed", last_error=str(last_error))
        logfire.log_exception("All LLM providers failed")
        raise RuntimeError(error_msg)

    def get_available_providers(self) -> list[str]:
        """Get list of available providers"""
        return [
            name for name, provider in self.providers.items() if provider.is_available()
        ]

    def set_primary_provider(self, provider_name: str):
        """Set the primary provider"""
        if provider_name in self.providers:
            self.primary_provider = provider_name
            self.logger.info("Primary provider updated", provider=provider_name)
        else:
            raise ValueError(f"Provider {provider_name} not available")


# Convenience function for easy initialization
def create_llm_client(
    primary: str = "llm_studio",
    fallbacks: list[str] | None = None,
    **provider_configs,
) -> MultiLLMClient:
    """Create a configured multi-LLM client"""
    client = MultiLLMClient(primary, fallbacks)

    # Add custom provider configurations
    for provider_name, config in provider_configs.items():
        if provider_name in ["openai", "replicate", "huggingface", "llm_studio"]:
            # Update existing provider with custom config
            pass  # TODO: Implement provider reconfiguration

    return client
