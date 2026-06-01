# Modal deployment: OpenAI-compatible vLLM servers for Parley agents.
#
# Serves one vLLM `/v1` endpoint per model in MODEL_REGISTRY, each as its own
# Modal class with its own GPU, persistent HF cache, and public URL. Agents
# (see backend/src/agents/llm_planner.py) point an AsyncOpenAI client at these
# endpoints to choose game actions.
#
# Every model in the roster is a REASONING model and is launched with a
# `--reasoning-parser`, so the OpenAI response carries the thinking trace in a
# separate `reasoning_content` field. The planner stores that trace per turn —
# we keep the reasoning, we don't throw it away.
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
#   label             short id used in the Modal class name + endpoint URL +
#                     OpenAI `model` field (matches --served-model-name)
#   hf_repo           Hugging Face repo id vLLM loads
#   gpu               Modal GPU spec ("H200" / "A100-80GB" / "H100" / "L40S")
#   tensor_parallel   number of GPUs (match gpu, e.g. "H200:2" + tp 2)
#   max_model_len     context cap — game state is tiny, but reasoning traces
#                     can be long, so leave generous headroom
#   reasoning_parser  vLLM --reasoning-parser value (separates the thinking
#                     trace into `reasoning_content`). None => trace stays
#                     inline in `content` and the planner extracts it.
#   extra_args        extra `vllm serve` flags this model needs
#   env               per-model env vars set before launch (e.g. MoE backend)
#
# All three are single-GPU, vLLM-native, reasoning models spanning three
# lineages (Qwen MoE / Google dense / Mistral dense). The giant MoEs
# (Kimi-K2 1T, GLM-5.x 754B, GLM-4.7 358B) are intentionally excluded: they are
# multi-GPU even quantized and add no value for choosing a JSON action list.
MODEL_REGISTRY: list[dict] = [
    {
        # Anchor: MoE 35B total / 3B active — frontier-ish quality at ~7B
        # speed/cost. Proven single-H200 BF16 (cf. voicescript qwen36 config).
        "label": "qwen36-a3b",
        "hf_repo": "Qwen/Qwen3.6-35B-A3B",
        "gpu": "H200",
        "tensor_parallel": 1,
        "max_model_len": 32768,
        "reasoning_parser": "qwen3",
        # Gated DeltaNet / MoE flags; --language-model-only skips the vision
        # tower (we only feed text). See voicescript qwen36_inference.py.
        "extra_args": [
            "--language-model-only",
            "--gdn-prefill-backend",
            "triton",
            "--trust-remote-code",
        ],
        # Force the Triton MoE backend: the FlashInfer CUTLASS path JIT-builds
        # trtllm_utils via ninja on first profile, which can blow past Modal's
        # startup window and SIGINT EngineCore mid-warmup.
        "env": {
            "VLLM_FUSED_MOE_BACKEND": "TRITON",
            "FLASHINFER_AUTOTUNER_DISABLE": "1",
        },
        "min_containers": 0,
        "scaledown_window": 300,
    },
    {
        # Dense 31B, different lineage. Gated repo — needs HF_TOKEN + license
        # acceptance on the HF model page with the token's account.
        "label": "gemma4-31b",
        "hf_repo": "google/gemma-4-31B-it",
        "gpu": "A100-80GB",
        "tensor_parallel": 1,
        "max_model_len": 32768,
        # No stable vLLM reasoning-parser name for Gemma-4 here; the planner
        # captures the trace inline (and always falls back to storing the raw
        # completion, so nothing is lost).
        "reasoning_parser": None,
        "extra_args": [],
        "env": {},
        "min_containers": 0,
        "scaledown_window": 300,
    },
    {
        # Dense 24B Mistral reasoning model — emits [THINK]...[/THINK]. Needs
        # the mistral tokenizer/config/load formats.
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
        "min_containers": 0,
        "scaledown_window": 300,
    },
]

VLLM_VERSION = "0.20.1"
VLLM_PORT = 8000
HF_CACHE_DIR = "/root/.cache/huggingface"
MINUTES = 60

# Recent vLLM on a CUDA devel base (mirrors the proven voicescript image) so
# the 2026 model architectures (Qwen3.6 GDN-MoE, Gemma-4, Magistral) load.
vllm_image = (
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

app = modal.App("parley-vllm")

# Persistent caches so weights download once and flashinfer JIT modules persist
# across cold starts (the latter avoids re-running ninja on every boot).
hf_cache = modal.Volume.from_name("parley-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("parley-vllm-cache", create_if_missing=True)
flashinfer_cache = modal.Volume.from_name(
    "parley-flashinfer-cache", create_if_missing=True
)

# Secrets created under the tuttinator profile (see header). HF_TOKEN is
# required for gated repos (Gemma); VLLM_API_KEY gates the /v1 endpoint — vLLM
# reads it from the env (do NOT pass --api-key on the CLI; vLLM echoes argv to
# the logs).
_secrets = [
    modal.Secret.from_name("huggingface"),
    modal.Secret.from_name("parley-vllm"),
]


def _build_server_class(entry: dict):
    """Create one Modal class serving ``entry``'s model on a vLLM /v1 endpoint.

    Returns ``(class_name, decorated_class)``; the caller binds it to a module
    global so ``modal deploy`` discovers it. Each class is given a distinct
    name so the models don't collide on the shared app.
    """
    label = entry["label"]
    hf_repo = entry["hf_repo"]

    class VLLMServer:
        @modal.enter()
        def start(self):
            """Launch the vLLM OpenAI-compatible server as a subprocess."""
            for key, value in entry.get("env", {}).items():
                os.environ.setdefault(key, value)

            if not os.environ.get("VLLM_API_KEY"):
                raise ValueError(
                    "VLLM_API_KEY not set — create the 'parley-vllm' secret "
                    "under the tuttinator profile."
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
                "--max-model-len",
                str(entry["max_model_len"]),
                "--tensor-parallel-size",
                str(entry.get("tensor_parallel", 1)),
            ]
            if entry.get("reasoning_parser"):
                cmd += ["--reasoning-parser", entry["reasoning_parser"]]
            cmd += list(entry.get("extra_args", []))

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

        @modal.web_server(port=VLLM_PORT, startup_timeout=30 * MINUTES)
        def serve(self):
            """Expose vLLM's HTTP server (the @modal.enter subprocess).

            First boot for a model downloads weights into the HF cache volume,
            which is why the startup timeout is generous; later cold starts read
            from the volume.
            """
            return

    # Each model needs a DISTINCT class identity, otherwise Modal registers
    # several classes all named "VLLMServer" on the same app and they collide.
    cls_name = f"VLLM_{label.replace('-', '_')}"
    VLLMServer.__name__ = cls_name
    VLLMServer.__qualname__ = cls_name
    decorated = app.cls(
        image=vllm_image,
        gpu=entry["gpu"],
        cpu=8,
        memory=131072,
        volumes={
            HF_CACHE_DIR: hf_cache,
            "/root/.cache/vllm": vllm_cache,
            "/root/.cache/flashinfer": flashinfer_cache,
        },
        secrets=_secrets,
        timeout=60 * MINUTES,
        scaledown_window=entry.get("scaledown_window", 300),
        min_containers=entry.get("min_containers", 0),
    )(VLLMServer)
    return cls_name, decorated


# Register one discoverable class per registry entry, binding each to a module
# global under its distinct name so `modal deploy` discovers it.
for _entry in MODEL_REGISTRY:
    _name, _cls = _build_server_class(_entry)
    globals()[_name] = _cls
