# Modal deployment: OpenAI-compatible vLLM servers for Parley agents.
#
# Serves one vLLM `/v1` endpoint per model in MODEL_REGISTRY, each as its own
# Modal class with its own GPU, persistent HF cache, and public URL. Agents
# (see backend/src/agents/llm_planner.py) point an AsyncOpenAI client at these
# endpoints to choose game actions.
#
# IMPORTANT: deploy under the `tuttinator` Modal profile, e.g.
#   MODAL_PROFILE=tuttinator uv run modal deploy agents/deploy/modal_vllm.py
#
# One-time secrets (also under the tuttinator profile):
#   MODAL_PROFILE=tuttinator uv run modal secret create huggingface HF_TOKEN=hf_xxx
#   MODAL_PROFILE=tuttinator uv run modal secret create parley-vllm VLLM_API_KEY=<random>
#
# After deploy, each model is reachable at:
#   https://<workspace>--parley-vllm-<label>-serve.modal.run/v1
# (find exact URLs in `modal app list` / the dashboard).

from __future__ import annotations

import os
import subprocess

import modal

# --- Model registry --------------------------------------------------------
#
# Single source of truth for which models we host. Each entry:
#   label            short id used in the Modal class name + endpoint URL
#   hf_repo          Hugging Face repo id vLLM loads
#   gpu              Modal GPU spec (A10G / L40S / "A100-40GB" / "A100-80GB" / "H100")
#   tensor_parallel  number of GPUs (set gpu="H100:2" etc. to match)
#   max_model_len    context cap (None → model default; lower = less VRAM)
#   quantization     vLLM --quantization value or None (e.g. "awq", "gptq")
#   extra_args       any extra `vllm serve` flags
#
# The defaults below are known-good, single-GPU, vLLM-compatible repos so a
# `modal deploy` works out of the box for the tracer bullet. Swap `hf_repo`
# to the exact newer 2026 versions (Qwen3.x, Gemma 4, GLM-4.x-flash,
# DeepSeek-v4-flash) once their repo ids are confirmed — nothing else changes.
MODEL_REGISTRY: list[dict] = [
    {
        # Tracer-bullet default: small, ungated, rock-solid on vLLM + A10G.
        "label": "qwen",
        "hf_repo": "Qwen/Qwen2.5-7B-Instruct",  # TODO: -> Qwen3.x when confirmed
        "gpu": "A10G",
        "tensor_parallel": 1,
        "max_model_len": 16384,
        "quantization": None,
        "extra_args": [],
        "min_containers": 0,
        "scaledown_window": 120,
    },
    {
        "label": "gemma",
        "hf_repo": "google/gemma-2-9b-it",  # gated: needs HF_TOKEN. TODO: Gemma 4
        "gpu": "L40S",
        "tensor_parallel": 1,
        "max_model_len": 8192,
        "quantization": None,
        "extra_args": [],
        "min_containers": 0,
        "scaledown_window": 120,
    },
    {
        "label": "glm-flash",
        "hf_repo": "THUDM/glm-4-9b-chat",  # TODO: -> GLM-4.x-flash when confirmed
        "gpu": "L40S",
        "tensor_parallel": 1,
        "max_model_len": 8192,
        "quantization": None,
        "extra_args": ["--trust-remote-code"],
        "min_containers": 0,
        "scaledown_window": 120,
    },
    {
        "label": "deepseek-flash",
        "hf_repo": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",  # TODO: DeepSeek-v4-flash
        "gpu": "A10G",
        "tensor_parallel": 1,
        "max_model_len": 16384,
        "quantization": None,
        "extra_args": [],
        "min_containers": 0,
        "scaledown_window": 120,
    },
]

VLLM_PORT = 8000
HF_CACHE_DIR = "/root/.cache/huggingface"

# Pin a recent vLLM. Bump as needed for newer model architectures.
vllm_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "vllm==0.6.6",
        "huggingface_hub[hf_transfer]",
    )
    .env({"HF_HOME": HF_CACHE_DIR, "HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

app = modal.App("parley-vllm")

# Persistent cache so model weights download once, not per cold start.
hf_cache = modal.Volume.from_name("parley-hf-cache", create_if_missing=True)

# Secrets created under the tuttinator profile (see header). The HF token is
# required for gated repos (e.g. Gemma); VLLM_API_KEY gates the /v1 endpoint.
_secrets = [
    modal.Secret.from_name("huggingface"),
    modal.Secret.from_name("parley-vllm"),
]


def _build_server_class(entry: dict):
    """Create one Modal class serving ``entry``'s model on a vLLM /v1 endpoint.

    Returns the class so the caller can register it under a module global —
    ``modal deploy`` only discovers classes bound at module scope.
    """
    label = entry["label"]
    hf_repo = entry["hf_repo"]

    @app.cls(
        name=f"parley-vllm-{label}",
        image=vllm_image,
        gpu=entry["gpu"],
        volumes={HF_CACHE_DIR: hf_cache},
        secrets=_secrets,
        timeout=60 * 60,
        scaledown_window=entry.get("scaledown_window", 120),
        min_containers=entry.get("min_containers", 0),
    )
    class VLLMServer:
        @modal.enter()
        def start(self):
            """Launch the vLLM OpenAI-compatible server as a subprocess."""
            cmd = [
                "vllm",
                "serve",
                hf_repo,
                "--host",
                "0.0.0.0",
                "--port",
                str(VLLM_PORT),
                "--served-model-name",
                label,
                "--tensor-parallel-size",
                str(entry.get("tensor_parallel", 1)),
            ]
            if entry.get("max_model_len"):
                cmd += ["--max-model-len", str(entry["max_model_len"])]
            if entry.get("quantization"):
                cmd += ["--quantization", entry["quantization"]]
            cmd += list(entry.get("extra_args", []))

            api_key = os.environ.get("VLLM_API_KEY")
            if api_key:
                cmd += ["--api-key", api_key]

            print("Launching:", " ".join(cmd))
            self.proc = subprocess.Popen(cmd)

        @modal.exit()
        def stop(self):
            proc = getattr(self, "proc", None)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()

        @modal.web_server(port=VLLM_PORT, startup_timeout=60 * 10)
        def serve(self):
            """Expose vLLM's HTTP server (the @modal.enter subprocess)."""
            # vLLM is already listening on VLLM_PORT; nothing to do here.
            return

    return VLLMServer


# Register one discoverable class per registry entry.
_SERVERS = {entry["label"]: _build_server_class(entry) for entry in MODEL_REGISTRY}
# Bind to module globals under CapWords names so `modal deploy` finds them.
for _label, _cls in _SERVERS.items():
    globals()[f"VLLM_{_label.replace('-', '_')}"] = _cls
