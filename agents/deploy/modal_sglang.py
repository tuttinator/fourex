# Modal deployment: OpenAI-compatible SGLang server for the Qwen3.6 agent.
#
# Serves `Qwen/Qwen3.6-35B-A3B-FP8` — an MoE checkpoint (35B total / 3B active)
# with a hybrid Gated-DeltaNet (linear-attention) + MoE architecture — on a
# SINGLE H100 via SGLang. This supersedes the old vLLM forced-Triton BF16 entry
# in modal_vllm.py (`qwen36-a3b`), which crawled at ~16 tok/s.
#
# Why SGLang + FP8 (see Downloads/moe-llm-serving-throughput-lessons.md):
#   - FP8 weights (~35 GB) fit one H100 with room for KV cache; near-zero quality
#     cost vs BF16 (~70 GB, needed an H200).
#   - The old setup forced the SLOW Triton fused-MoE backend purely to dodge a
#     startup JIT-compile timeout. The right fix is to keep the FAST FP8 DeepGEMM
#     kernels and move the one-time compile OFF the hot path: we run
#     `sglang.compile_deep_gemm` at BUILD time into a persistent `deepgemm-cache`
#     volume, so every cold start is a cache hit.
#   - A head-to-head benchmark on H100/FP8 (512 tok/req) had SGLang win decisively
#     vs vLLM 0.22 — 1.3x / 1.5x / 3.8x aggregate throughput at concurrency
#     1 / 8 / 32, with TTFT staying ~1.3 s while vLLM blew out to ~29 s at conc 32.
#
# The served model name is `qwen36-a3b`, matching the label the autonomous match
# runner expects — point `PARLEY_VLLM_QWEN36_A3B_URL` at this endpoint's /v1 and
# the runner uses it with no code change (it only needs an OpenAI base_url + key).
#
# IMPORTANT: deploy under the `tuttinator` Modal profile, AND with image builder
# 2025.06+ — the LEGACY builder force-installs its own fastapi 0.88 + pydantic v1
# `modal_requirements.txt`, which downgrades this image's pydantic 2.x and breaks
# SGLang at import (`cannot import name 'field_validator' from pydantic`). 2025.06
# doesn't inject those, so SGLang's own pydantic v2 / fastapi survive:
#   MODAL_PROFILE=tuttinator MODAL_IMAGE_BUILDER_VERSION=2025.06 \
#     uv run modal deploy agents/deploy/modal_sglang.py
#
# One-time secrets (also under the tuttinator profile):
#   MODAL_PROFILE=tuttinator uv run modal secret create huggingface HF_TOKEN=hf_xxx
#   MODAL_PROFILE=tuttinator uv run modal secret create parley-vllm VLLM_API_KEY=<random>
#
# After deploy the endpoint is:
#   https://tuttinator--parley-sglang-serve.modal.run/v1
# (confirm the exact URL in the deploy output / `modal app list`).

from __future__ import annotations

import os
import subprocess

import modal

# --- Config ----------------------------------------------------------------

# FP8 release — half the memory of BF16, fits a single H100, negligible quality
# loss. The hybrid GDN+MoE arch is why the old BF16 path was so JIT-heavy.
MODEL_NAME = "Qwen/Qwen3.6-35B-A3B-FP8"
MODEL_REVISION = "main"
# Served under the runner's label so it wires in unchanged. NB: SGLang rejects a
# colon in --served-model-name, so we can't register a second `llm` alias here
# (vLLM allowed `--served-model-name name llm`); the planner sends this exact id.
SERVED_MODEL_NAME = "qwen36-a3b"

N_GPU = 1
GPU = "H100"
PORT = 8000
MINUTES = 60
# Game state + reasoning traces are small; 64k is ample and leaves more of the
# H100 for KV cache than the model card's 262k default.
CONTEXT_LENGTH = 65536

app = modal.App("parley-sglang")

# Persistent caches. Per lessons sharp-edge #4, the DeepGEMM JIT cache is kept on
# its OWN volume (distinct from any vLLM deepgemm cache) so the two frameworks
# don't pollute each other's `~/.cache/deep_gemm`.
HF_CACHE_DIR = "/root/.cache/huggingface"
DG_CACHE_DIR = "/root/.cache/deep_gemm"
hf_cache = modal.Volume.from_name("parley-hf-cache", create_if_missing=True)
deepgemm_cache = modal.Volume.from_name(
    "parley-sglang-deepgemm-cache", create_if_missing=True
)

# Secrets created under the tuttinator profile. HF_TOKEN gates the (ungated, but
# token never hurts) download; VLLM_API_KEY gates the /v1 endpoint — the runner
# sends it as a Bearer token. SGLang has no env-var for the key (source default
# is None), so we pass --api-key but redact it from our own launch log.
_hf_secret = modal.Secret.from_name("huggingface")
_vllm_secret = modal.Secret.from_name("parley-vllm")
_secrets = [_hf_secret, _vllm_secret]


def _prefetch_weights() -> None:
    """Download FP8 weights into the HF cache at build time (CPU, cheap)."""
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_NAME,
        revision=MODEL_REVISION,
        ignore_patterns=["*.pth", "original/*"],
    )


def _compile_deep_gemm() -> None:
    """Pre-compile the FP8 DeepGEMM MoE kernels into the cache volume.

    This is the clean replacement for the old forced-Triton hack: the JIT
    happens ONCE here at build (on a GPU), persists in `deepgemm-cache`, and
    every later cold start reads the cache instead of compiling on the hot path.
    It is an OFFLINE compiler (no server bound) — safe inside a build step,
    unlike booting a full `vllm serve` / `launch_server` (lessons sharp-edge #1).
    """
    subprocess.run(
        [
            "python3",
            "-m",
            "sglang.compile_deep_gemm",
            "--model-path",
            MODEL_NAME,
            "--revision",
            MODEL_REVISION,
            "--tp",
            str(N_GPU),
        ],
        check=True,
    )


# Image: SGLang runtime matching Modal's own example for this exact model.
# Use the image's OWN huggingface_hub (1.9.2) + hf-xet — do NOT pip-install an
# older pinned hf_hub: downgrading to 0.34 breaks transformers 5.3.0 (needs
# >=1.3.0) AND fails the full xet-backed safetensors download (it can fetch a
# small config.json but chokes on the large xet blobs). hf-xet already gives the
# fast download path, so HF_HUB_ENABLE_HF_TRANSFER / hf_transfer aren't needed.
sglang_image = (
    modal.Image.from_registry("lmsysorg/sglang:v0.5.10.post1-cu130-runtime")
    .entrypoint([])
    .env({"HF_HOME": HF_CACHE_DIR})
    # Prefetch on CPU (cheap), then compile DeepGEMM on a GPU (needs the device
    # to emit FP8 kernels for the target arch). Both mount the HF cache.
    .run_function(
        _prefetch_weights,
        volumes={HF_CACHE_DIR: hf_cache},
        secrets=[_hf_secret],
        timeout=60 * MINUTES,
    )
    .run_function(
        _compile_deep_gemm,
        gpu=GPU,
        volumes={HF_CACHE_DIR: hf_cache, DG_CACHE_DIR: deepgemm_cache},
        secrets=[_hf_secret],
        timeout=60 * MINUTES,
    )
)


@app.function(
    image=sglang_image,
    gpu=f"{GPU}:{N_GPU}",
    cpu=8,
    memory=131072,
    volumes={HF_CACHE_DIR: hf_cache, DG_CACHE_DIR: deepgemm_cache},
    secrets=_secrets,
    timeout=60 * MINUTES,
    # Scale to zero when idle (limited Modal credits). Flip to 1 to keep one warm
    # during an active match run — cold starts still pay weight load + CUDA-graph
    # capture (~minutes) and 303 at Modal's edge until ready.
    min_containers=0,
    scaledown_window=600,
)
@modal.concurrent(max_inputs=32)
# 15-min startup cap (NOT 60): cold start is weight load (~35 GB from the volume)
# + DeepGEMM cache read + CUDA-graph capture + warmup, which all completed inside
# a couple of minutes during the build. A long timeout is a footgun — if the
# launch dies (e.g. a bad arg), Popen still returns 0 and Modal would otherwise
# hold an H100 for the full timeout waiting for a port that never opens.
@modal.web_server(port=PORT, startup_timeout=15 * MINUTES)
def serve() -> None:
    api_key = os.environ.get("VLLM_API_KEY")
    if not api_key:
        raise ValueError(
            "VLLM_API_KEY not set — create the 'parley-vllm' secret under the "
            "tuttinator profile."
        )

    # This hybrid GDN+MoE model needs extra_buffer for its mamba/linear-attn
    # cache, and EAGLE speculative decoding + radix cache is only compatible with
    # extra_buffer when SPEC_V2 is enabled (SGLang asserts this otherwise).
    os.environ.setdefault("SGLANG_ENABLE_SPEC_V2", "1")

    cmd = [
        "python3",
        "-m",
        "sglang.launch_server",
        "--model-path",
        MODEL_NAME,
        "--revision",
        MODEL_REVISION,
        "--served-model-name",
        SERVED_MODEL_NAME,
        "--host",
        "0.0.0.0",
        "--port",
        str(PORT),
        "--tp-size",
        str(N_GPU),
        "--context-length",
        str(CONTEXT_LENGTH),
        "--mem-fraction-static",
        "0.8",
        # Keep the reasoning trace in `reasoning_content` so the planner stores
        # the thinking separately from the action JSON.
        "--reasoning-parser",
        "qwen3",
        "--tool-call-parser",
        "qwen3_coder",
        # FP8 DeepGEMM MoE kernels are pre-compiled into the cache volume above;
        # SGLang reads them here instead of building on the hot path.
        "--mamba-scheduler-strategy",
        "extra_buffer",
        # MTP speculative decoding via the model's built-in NEXTN head — the
        # HF model card's exact SGLang recipe. ALL THREE params must be set
        # together: if you set --speculative-num-steps but omit topk/draft-tokens,
        # SGLang skips auto-filling them (they stay None) and then crashes on
        # `speculative_eagle_topk > 1` (None > 1). With SPEC_V2 + EAGLE/NEXTN,
        # topk MUST be 1; draft-tokens = num_steps + 1.
        "--speculative-algo",
        "NEXTN",
        "--speculative-num-steps",
        "3",
        "--speculative-eagle-topk",
        "1",
        "--speculative-num-draft-tokens",
        "4",
        # API key last so we can redact just this pair from the printed command.
        "--api-key",
        api_key,
    ]

    # Launch with an argv LIST, never a shell string: a shell would shatter any
    # arg containing spaces/JSON (lessons sharp-edge #2). Redact the key in logs.
    redacted = [("***" if a == api_key else a) for a in cmd]
    print("Launching:", " ".join(redacted))
    subprocess.Popen(cmd)
