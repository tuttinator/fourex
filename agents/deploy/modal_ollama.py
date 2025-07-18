# ---
# ---
# Sourced from and slightly modified from: https://github.com/modal-labs/modal-examples/blob/main/06_gpu_and_ml/llm-serving/ollama.py


import asyncio
import subprocess

import modal

# ## Configuration and Constants

# Directory for Ollama models within the container and volume
MODEL_DIR = "/ollama_models"

# Define the models we want to work with
# You can specify different model versions using the format "model:tag"
# Check out available models on Ollama's website:
# https://ollama.com/search
MODELS_TO_DOWNLOAD = [
    "gemma3:12b",
    "qwen3:32b",
    # "llama3.1:70b",
    # "mistral-nemo:12b",
]  # Downloaded at startup

# Ollama version to install - you may need to update this for the latest models
OLLAMA_VERSION = "0.9.6"  # Update to the latest version as needed
# Ollama's default port - we'll expose this through Modal
OLLAMA_PORT = 11434

GPU_TYPE = "A10G"  # GPU type to use for the Ollama server
# You can change this to any supported GPU type based on your needs and Modal's offerings.
# Other otions:
# T4
# L4
# A10G
# A100-40GB
# A100-80GB
# L40S
# H100
# H200
# B200
# Check out the pricing
# https://modal.com/pricing

# ## Building the Container Image

# First, we create a Modal Image that includes Ollama and its dependencies.
# We use the official Ollama installation script to set up the Ollama binary.

ollama_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("curl", "ca-certificates")
    .pip_install(
        "fastapi==0.115.8",
        "uvicorn[standard]==0.34.0",
        "openai~=1.30",  # Pin OpenAI version for compatibility
    )
    .run_commands(
        "echo 'Installing Ollama...'",
        f"OLLAMA_VERSION={OLLAMA_VERSION} curl -fsSL https://ollama.com/install.sh | sh",
        "echo 'Ollama installed at $(which ollama)'",
        f"mkdir -p {MODEL_DIR}",
    )
    .env(
        {
            # Configure Ollama to serve on its default port
            "OLLAMA_HOST": f"0.0.0.0:{OLLAMA_PORT}",
            "OLLAMA_MODELS": MODEL_DIR,  # Tell Ollama where to store models
        }
    )
)

# Create a Modal App, which groups our functions together
app = modal.App("ollama-server", image=ollama_image)

# ## Persistent Storage for Models

# We use a Modal Volume to cache downloaded models between runs.
# This prevents needing to re-download large model files each time.

model_volume = modal.Volume.from_name("ollama-models-store", create_if_missing=True)

# ## The Ollama Server Class

# We define an OllamaServer class to manage the Ollama process.
# This class handles:
# - Starting the Ollama server
# - Downloading required models
# - Exposing the API via Modal's web_server
# - Running test requests against the served models


@app.cls(
    gpu=GPU_TYPE,
    volumes={MODEL_DIR: model_volume},  # Mount our model storage
    timeout=60 * 5,  # 5 minutes max input runtime
    min_containers=1,  # Keep at least one container running for fast startup
)
class OllamaServer:
    ollama_process: subprocess.Popen | None = None

    @modal.enter()
    async def start_ollama(self):
        """Starts the Ollama server and ensures required models are downloaded."""
        print("Starting Ollama setup...")

        print(f"Starting Ollama server on port {OLLAMA_PORT}...")
        cmd = ["ollama", "serve"]
        self.ollama_process = subprocess.Popen(cmd)
        print(f"Ollama server started with PID: {self.ollama_process.pid}")

        # Wait for server to initialize
        await asyncio.sleep(10)
        print("Ollama server should be ready.")

        # --- Model Management ---
        # Check which models are already downloaded, and pull any that are missing
        loop = asyncio.get_running_loop()
        models_pulled = False

        # Get list of currently available models
        ollama_list_proc = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True
        )

        if ollama_list_proc.returncode != 0:
            print(f"Error: 'ollama list' failed: {ollama_list_proc.stderr}")
            raise RuntimeError(
                f"Failed to list Ollama models: {ollama_list_proc.stderr}"
            )

        current_models_output = ollama_list_proc.stdout
        print("Current models detected:", current_models_output)

        # Download each requested model if not already present
        for model_name in MODELS_TO_DOWNLOAD:
            print(f"Checking for model: {model_name}")
            model_tag_to_check = (
                model_name if ":" in model_name else f"{model_name}:latest"
            )

            if model_tag_to_check not in current_models_output:
                print(
                    f"Model '{model_name}' not found. Pulling (output will stream directly)..."
                )
                models_pulled = True  # Mark that a pull is happening

                # Pull the model - this can take a while for large models
                pull_process = await asyncio.create_subprocess_exec(
                    "ollama",
                    "pull",
                    model_name,
                )

                # Wait for the pull process to complete
                retcode = await pull_process.wait()

                if retcode != 0:
                    print(f"Error pulling model '{model_name}': exit code {retcode}")
                else:
                    print(f"Model '{model_name}' pulled successfully.")
            else:
                print(f"Model '{model_name}' already exists.")

            # Commit the volume only if we actually pulled new models
            if models_pulled:
                print("Committing model volume...")
                await loop.run_in_executor(None, model_volume.commit)
                print("Volume commit finished.")

        print("Ollama setup complete.")

    @modal.exit()
    def stop_ollama(self):
        """Terminates the Ollama server process on shutdown."""
        print("Shutting down Ollama server...")
        if self.ollama_process and self.ollama_process.poll() is None:
            print(f"Terminating Ollama server (PID: {self.ollama_process.pid})...")
            try:
                self.ollama_process.terminate()
                self.ollama_process.wait(timeout=10)
                print("Ollama server terminated.")
            except subprocess.TimeoutExpired:
                print("Ollama server kill required.")
                self.ollama_process.kill()
                self.ollama_process.wait()
            except Exception as e:
                print(f"Error shutting down Ollama server: {e}")
        else:
            print("Ollama server process already exited or not found.")
        print("Shutdown complete.")

    @modal.web_server(port=OLLAMA_PORT, startup_timeout=180)
    def serve(self):
        """
        Exposes the Ollama server's API endpoints through Modal's web_server.

        This is the key function that makes Ollama's API accessible over the internet.
        The web_server decorator maps Modal's HTTPS endpoint to Ollama's internal port.
        """
        print(f"Serving Ollama API on port {OLLAMA_PORT}")


# ## Deploying to Production
# ```bash
# modal deploy ollama.py
# ```
#
# This creates a persistent deployment that:
#
# 1. Provides a stable URL endpoint for your Ollama API
# 2. Keeps at least one container warm for fast responses
# 3. Scales automatically based on usage
# 4. Preserves your models in the persistent volume between invocations
#
# After deployment, you can find your endpoint URL in your Modal dashboard.
#
# You can then use this endpoint with any OpenAI-compatible client by setting:
#
# ```
# OPENAI_API_BASE=https://your-endpoint-url/v1
# OPENAI_API_KEY=any-value  # Ollama doesn't require authentication
# ```
