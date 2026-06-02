# Modal deployment: OpenAI-compatible vLLM servers for Parley agents.
#
# Serves one vLLM `/v1` endpoint per model in MODEL_REGISTRY, each as its own
# Modal web function with its own GPU, prefetched weights, persistent caches,
# and public URL. Agents (backend/src/agents/llm_planner.py) point an
# AsyncOpenAI client at these endpoints to choose game actions.
#
# Structure mirrors the proven voicescript qwen36_inference.py:
#   - weights are PREFETCHED into the image at build time (snapshot_download in
#     a run_function), so cold starts don't wait on a 72 GB download;
#   - a persistent flashinfer-cache volume + a 60-minute startup_timeout let the
#     FlashInfer CUTLASS MoE ninja JIT build complete once and persist, instead
#     of being SIGINT'd mid-warmup on every cold start (the crash we hit before);
#   - @modal.concurrent batches multiple game requests onto one warm container.
#
# Every model is a REASONING model, launched with a `--reasoning-parser` so the
# OpenAI response carries the thinking trace in `reasoning_content`; the planner
# stores that per turn. We keep the reasoning, we don't throw it away.
#
# IMPORTANT: deploy under the `tuttinator` Modal profile, e.g.
#   MODAL_PROFILE=tuttinator uv run modal deploy agents/deploy/modal_vllm.py
#
# One-time secrets (also under the tuttinator profile):
#   MODAL_PROFILE=tuttinator uv run modal secret create huggingface HF_TOKEN=hf_xxx
#   MODAL_PROFILE=tuttinator uv run modal secret create parley-vllm VLLM_API_KEY=<random>
#
# After deploy, each model is reachable at:
#   https://<workspace>--parley-vllm-serve-<label>.modal.run/v1
# (find exact URLs in the deploy output / `modal app list`).

from __future__ import annotations

import os
import subprocess

import modal

# --- Model registry --------------------------------------------------------
#
# Single source of truth for which models we host. Each entry:
#   label             short id used in the function name + endpoint URL +
#                     OpenAI `model` field (matches --served-model-name)
#   hf_repo           Hugging Face repo id vLLM loads
#   gpu               Modal GPU spec ("H200" / "A100-80GB" / "H100" / "L40S")
#   tensor_parallel   number of GPUs (match gpu, e.g. "H200:2" + tp 2)
#   max_model_len     context cap (game state is tiny; reasoning traces aren't)
#   reasoning_parser  vLLM --reasoning-parser value (separates the trace into
#                     reasoning_content). None => trace stays inline in content.
#   extra_args        extra `vllm serve` flags this model needs
#   env               per-model env vars set before launch
#   ignore_patterns   files snapshot_download skips during prefetch (keep the
#                     format the launch flags load: HF safetensors vs mistral)
#   max_inputs        @modal.concurrent batch cap per container
#
# These are single-GPU, vLLM-native dense reasoning models (Google + Mistral +
# small distills). The Qwen3.6 MoE anchor now lives in modal_sglang.py (SGLang
# FP8). Giant MoEs (Kimi-K2 1T, GLM-5.x 754B, GLM-4.7 358B) are excluded:
# multi-GPU even quantized, no gameplay gain.
MODEL_REGISTRY: list[dict] = [
    # NOTE: the Qwen3.6-35B-A3B anchor moved to SGLang + FP8 — see
    # agents/deploy/modal_sglang.py. The old vLLM BF16 entry here forced the slow
    # Triton fused-MoE backend (to dodge a startup JIT timeout) and crawled at
    # ~16 tok/s; the SGLang FP8 deployment pre-compiles DeepGEMM at build and is
    # several times faster. It still serves under `--served-model-name qwen36-a3b`,
    # so the runner is unchanged — just point PARLEY_VLLM_QWEN36_A3B_URL at it.
    {
        # Dense 31B, different lineage. Gated — needs HF_TOKEN + license
        # acceptance on the HF page with the token's account.
        "label": "gemma4-31b",
        "hf_repo": "google/gemma-4-31B-it",
        "gpu": "A100-80GB",
        "tensor_parallel": 1,
        "max_model_len": 32768,
        # No stable vLLM reasoning-parser name for Gemma-4 here; the planner
        # captures the trace inline (and always stores the raw completion as a
        # fallback, so nothing is lost).
        "reasoning_parser": None,
        "extra_args": [],
        "env": {},
        "ignore_patterns": ["*.gguf", "*.pth", "original/*"],
        "min_containers": 0,
        "scaledown_window": 300,
        "max_inputs": 32,
    },
    {
        # Dense 24B Mistral reasoning model — emits [THINK]...[/THINK]. Needs the
        # mistral tokenizer/config/load formats, so keep the consolidated files.
        "label": "magistral-small",
        "hf_repo": "mistralai/Magistral-Small-2509",
        "gpu": "A100-80GB",
        "tensor_parallel": 1,
        "max_model_len": 32768,
        "reasoning_parser": "mistral",
        "extra_args": [
            "--tokenizer-mode",
            "mistral",
            "--config-format",
            "mistral",
            "--load-format",
            "mistral",
        ],
        "env": {},
        "ignore_patterns": ["*.gguf"],
        "min_containers": 0,
        "scaledown_window": 600,
        "max_inputs": 32,
    },
    {
        # Small + fast reasoning distill (R1 chain-of-thought into Qwen3-8B).
        # Dense, Qwen3 arch (native in vLLM, no trust-remote-code) → no MoE
        # kernel pain, serves at high throughput on a cheap A10G. Ungated.
        "label": "deepseek-r1-qwen3-8b",
        "hf_repo": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        "gpu": "A10G",
        "tensor_parallel": 1,
        "max_model_len": 16384,
        "reasoning_parser": "deepseek_r1",
        "extra_args": [],
        "env": {},
        "ignore_patterns": ["*.gguf", "*.pth", "original/*"],
        # NOTE: R1-distill over-reasons (11k+ char traces) and rarely finishes
        # the JSON answer within a sane token budget → always falls back. Keep
        # at 0; only useful with a hard reasoning-token bound. Magistral is the
        # better balance (concise reasoning + actual actions).
        "min_containers": 0,
        "scaledown_window": 600,
        "max_inputs": 32,
    },
    {
        # Tiny 4B dense reasoner — reasons by default. vLLM has no built-in
        # Nemotron-3 reasoning parser, so serve parser-less and let the planner
        # capture the inline <think> trace. May be gated (needs HF license
        # acceptance on the NVIDIA repo with the token's account).
        "label": "nemotron-nano-4b",
        "hf_repo": "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
        "gpu": "A10G",
        "tensor_parallel": 1,
        "max_model_len": 16384,
        "reasoning_parser": None,
        "extra_args": ["--trust-remote-code"],
        "env": {},
        "ignore_patterns": ["*.gguf", "*.pth", "original/*"],
        # NOTE: only ~3.7 tok/s on vLLM 0.20.1 (unoptimized trust-remote-code
        # path for the Nemotron-3 arch) — effectively unusable. Keep at 0.
        "min_containers": 0,
        "scaledown_window": 600,
        "max_inputs": 32,
    },
]

VLLM_VERSION = "0.20.1"
VLLM_PORT = 8000
HF_CACHE_DIR = "/root/.cache/huggingface"
MINUTES = 60

app = modal.App("parley-vllm")

# Persistent caches: weights download once; flashinfer JIT modules persist
# across cold starts (so ninja doesn't re-build trtllm/cutlass every boot).
# NOTE: we deliberately do NOT persist vLLM's torch.compile cache — loading the
# cached AOT artifact back off a Modal (9P) volume hangs the engine after
# compile. With --enforce-eager we don't compile at all, so it's moot anyway.
hf_cache = modal.Volume.from_name("parley-hf-cache", create_if_missing=True)
flashinfer_cache = modal.Volume.from_name(
    "parley-flashinfer-cache", create_if_missing=True
)

# Secrets created under the tuttinator profile (see header). HF_TOKEN is needed
# for gated repos (Gemma, Mistral) at both prefetch and serve time; VLLM_API_KEY
# gates the /v1 endpoint — vLLM reads it from the env (do NOT pass --api-key on
# the CLI; vLLM echoes argv to the logs).
_hf_secret = modal.Secret.from_name("huggingface")
_vllm_secret = modal.Secret.from_name("parley-vllm")
_secrets = [_hf_secret, _vllm_secret]

# Base image: recent vLLM on a CUDA devel base (mirrors the proven voicescript
# image) so the 2026 architectures (Qwen3.6 GDN-MoE, Gemma-4, Magistral) load.
_base_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-devel-ubuntu22.04",
        add_python="3.12",
    )
    .entrypoint([])
    .uv_pip_install(
        f"vllm=={VLLM_VERSION}",
        "huggingface_hub[hf_transfer]==0.34",
    )
    .env({"HF_HOME": HF_CACHE_DIR, "HF_HUB_ENABLE_HF_TRANSFER": "1"})
)


def _prefetch_weights() -> None:
    """Warm the HF cache for one repo during image build.

    Module-level (Modal requires run_function targets be importable globals).
    The repo + ignore patterns are passed via image env vars set in
    ``_image_for``; the HF cache volume is mounted so weights persist and cold
    starts skip the multi-GB download.
    """
    import os as _os

    from huggingface_hub import snapshot_download

    repo = _os.environ["PREFETCH_REPO"]
    ignore = [p for p in _os.environ.get("PREFETCH_IGNORE", "").split(",") if p]
    snapshot_download(repo_id=repo, ignore_patterns=ignore or None)


def _image_for(entry: dict):
    """Per-model image that prefetches that model's weights into the HF cache."""
    return _base_image.env(
        {
            "PREFETCH_REPO": entry["hf_repo"],
            "PREFETCH_IGNORE": ",".join(entry.get("ignore_patterns", [])),
        }
    ).run_function(
        _prefetch_weights,
        volumes={HF_CACHE_DIR: hf_cache},
        secrets=[_hf_secret],
        timeout=60 * MINUTES,
    )


def _make_serve(entry: dict):
    """Build the web-server function that launches vLLM for ``entry``."""
    label = entry["label"]
    hf_repo = entry["hf_repo"]

    def _serve() -> None:
        for key, value in entry.get("env", {}).items():
            os.environ.setdefault(key, value)

        if not os.environ.get("VLLM_API_KEY"):
            raise ValueError(
                "VLLM_API_KEY not set — create the 'parley-vllm' secret under "
                "the tuttinator profile."
            )

        cmd = [
            "vllm",
            "serve",
            hf_repo,
            "--served-model-name",
            label,
            "--host",
            "0.0.0.0",
            "--port",
            str(VLLM_PORT),
            "--uvicorn-log-level=info",
            "--max-model-len",
            str(entry["max_model_len"]),
            "--tensor-parallel-size",
            str(entry.get("tensor_parallel", 1)),
        ]
        if entry.get("reasoning_parser"):
            cmd += ["--reasoning-parser", entry["reasoning_parser"]]
        cmd += list(entry.get("extra_args", []))

        print("Launching:", " ".join(cmd))
        # Launch with an argv LIST, never a shell string: a shell mangles any arg
        # containing spaces/quotes/JSON (e.g. --speculative-config) — lessons
        # sharp-edge #2. vLLM reads VLLM_API_KEY from the env (we never pass it on
        # the CLI). Popen returns immediately; Modal then waits for the port to
        # open (up to startup_timeout) while vLLM loads + builds.
        subprocess.Popen(cmd)

    # Distinct name per model so each gets its own deployed function + URL.
    _serve.__name__ = f"serve_{label.replace('-', '_')}"
    _serve.__qualname__ = _serve.__name__

    decorated = app.function(
        image=_image_for(entry),
        gpu=entry["gpu"],
        cpu=8,
        memory=131072,
        volumes={
            HF_CACHE_DIR: hf_cache,
            "/root/.cache/flashinfer": flashinfer_cache,
        },
        secrets=_secrets,
        timeout=60 * MINUTES,
        scaledown_window=entry.get("scaledown_window", 300),
        min_containers=entry.get("min_containers", 0),
        # _serve is a per-model closure (not a global), so cloudpickle it.
        serialized=True,
    )(
        modal.concurrent(max_inputs=entry.get("max_inputs", 32))(
            modal.web_server(port=VLLM_PORT, startup_timeout=60 * MINUTES)(_serve)
        )
    )
    return _serve.__name__, decorated


# Register one discoverable web function per registry entry.
for _entry in MODEL_REGISTRY:
    _name, _fn = _make_serve(_entry)
    globals()[_name] = _fn
