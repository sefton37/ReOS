"""Ollama handlers.

Manages Ollama LLM settings, model pulling, and connection testing.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from reos.db import Database
from reos.rpc.router import register
from reos.rpc.types import INVALID_PARAMS, RpcError

logger = logging.getLogger(__name__)

# Global dict to track ongoing pulls
_active_pulls: dict[str, dict[str, Any]] = {}
_pull_lock = threading.Lock()


def _detect_system_hardware() -> dict[str, Any]:
    """Detect system hardware for model recommendations."""
    import subprocess

    result = {
        "ram_gb": 0,
        "gpu_available": False,
        "gpu_name": None,
        "gpu_vram_gb": None,
        "gpu_type": None,
        "recommended_max_params": "3b",
    }

    # Detect RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    result["ram_gb"] = round(kb / 1024 / 1024, 1)
                    break
    except Exception as e:
        logger.debug("Failed to detect RAM: %s", e)

    # Detect NVIDIA GPU
    try:
        nvidia_out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if nvidia_out.returncode == 0 and nvidia_out.stdout.strip():
            lines = nvidia_out.stdout.strip().split("\n")
            if lines:
                parts = lines[0].split(", ")
                if len(parts) >= 2:
                    result["gpu_available"] = True
                    result["gpu_type"] = "nvidia"
                    result["gpu_name"] = parts[0].strip()
                    result["gpu_vram_gb"] = round(int(parts[1]) / 1024, 1)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug("Failed to detect NVIDIA GPU: %s", e)

    return result


@register("ollama/status", needs_db=True)
def handle_status(db: Database) -> dict[str, Any]:
    """Get Ollama connection status and current settings."""
    from reos.ollama import check_ollama, list_ollama_models
    from reos.settings import settings

    # Get stored settings
    stored_url = db.get_state(key="ollama_url")
    stored_model = db.get_state(key="ollama_model")
    stored_gpu_enabled = db.get_state(key="ollama_gpu_enabled")
    stored_num_ctx = db.get_state(key="ollama_num_ctx")

    url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url
    model = stored_model if isinstance(stored_model, str) and stored_model else settings.ollama_model
    gpu_enabled = stored_gpu_enabled != "false"  # Default to true
    num_ctx = int(stored_num_ctx) if isinstance(stored_num_ctx, str) and stored_num_ctx.isdigit() else None

    # Check connection
    health = check_ollama(url=url)

    # List models if reachable
    models: list[str] = []
    if health.reachable:
        try:
            models = list_ollama_models(url=url)
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)

    # Get hardware info
    hardware = _detect_system_hardware()

    return {
        "url": url,
        "model": model,
        "reachable": health.reachable,
        "model_count": health.model_count,
        "error": health.error,
        "available_models": models,
        "gpu_enabled": gpu_enabled,
        "gpu_available": hardware["gpu_available"],
        "gpu_name": hardware["gpu_name"],
        "gpu_vram_gb": hardware["gpu_vram_gb"],
        "num_ctx": num_ctx,
        "hardware": hardware,
    }


@register("ollama/set_url", needs_db=True)
def handle_set_url(db: Database, *, url: str) -> dict[str, Any]:
    """Set Ollama URL."""
    from reos.ollama import check_ollama

    # Validate URL format
    if not url.startswith(("http://", "https://")):
        raise RpcError(code=INVALID_PARAMS, message="URL must start with http:// or https://")

    # Test connection
    health = check_ollama(url=url)
    if not health.reachable:
        raise RpcError(code=-32010, message=f"Cannot connect to Ollama at {url}: {health.error}")

    db.set_state(key="ollama_url", value=url)
    return {"ok": True, "url": url}


@register("ollama/set_model", needs_db=True)
def handle_set_model(db: Database, *, model: str) -> dict[str, Any]:
    """Set active Ollama model."""
    from reos.ollama import list_ollama_models
    from reos.settings import settings

    stored_url = db.get_state(key="ollama_url")
    url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url

    # Verify model exists
    available = list_ollama_models(url=url)
    if model not in available:
        raise RpcError(code=INVALID_PARAMS, message=f"Model '{model}' not found. Available: {', '.join(available[:5])}")

    db.set_state(key="ollama_model", value=model)
    return {"ok": True, "model": model}


@register("ollama/model_info", needs_db=True)
def handle_model_info(db: Database, *, model: str) -> dict[str, Any]:
    """Get detailed info about a model (params, context length, capabilities)."""
    import httpx
    from reos.settings import settings

    stored_url = db.get_state(key="ollama_url")
    url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url
    show_url = url.rstrip("/") + "/api/show"

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(show_url, json={"name": model})
            res.raise_for_status()
            data = res.json()

            # Extract relevant info
            details = data.get("details", {})
            model_info = data.get("model_info", {})
            parameters = data.get("parameters", "")
            template = data.get("template", "")
            modelfile = data.get("modelfile", "")

            # Parse parameter count from details or model name
            param_size = details.get("parameter_size", "")
            if not param_size:
                # Try to extract from model name (e.g., "llama3.1:8b" -> "8B")
                for part in model.replace(":", "-").replace("_", "-").split("-"):
                    part_lower = part.lower()
                    if part_lower.endswith("b") and part_lower[:-1].replace(".", "").isdigit():
                        param_size = part.upper()
                        break

            # Get context length from model_info or parameters
            context_length = None
            for key in model_info:
                if "context" in key.lower():
                    val = model_info[key]
                    if isinstance(val, (int, float)):
                        context_length = int(val)
                        break

            # Also check parameters string for num_ctx
            if context_length is None and "num_ctx" in parameters:
                for line in parameters.split("\n"):
                    if "num_ctx" in line:
                        try:
                            context_length = int(line.split()[-1])
                        except (ValueError, IndexError) as e:
                            logger.debug("Failed to parse num_ctx: %s", e)

            # Default context lengths by model family
            if context_length is None:
                model_lower = model.lower()
                if "llama3" in model_lower or "llama-3" in model_lower:
                    context_length = 8192
                elif "mistral" in model_lower:
                    context_length = 32768
                elif "codellama" in model_lower:
                    context_length = 16384
                else:
                    context_length = 2048  # Conservative default

            # Detect capabilities
            capabilities = {
                "vision": False,
                "tools": False,
                "thinking": False,
                "embedding": False,
            }

            model_lower = model.lower()
            template_lower = template.lower()
            families = details.get("families", [])

            # Vision capability
            if any("vision" in str(v).lower() or "clip" in str(v).lower()
                   for v in model_info.values()):
                capabilities["vision"] = True
            if "llava" in model_lower or "vision" in model_lower or "bakllava" in model_lower:
                capabilities["vision"] = True
            if "clip" in families:
                capabilities["vision"] = True

            # Tools capability
            tool_markers = ["<tool_call>", "<function_call>", "[TOOL]", "{{.ToolCall}}", "tools"]
            if any(marker.lower() in template_lower for marker in tool_markers):
                capabilities["tools"] = True
            if any(name in model_lower for name in ["llama3.1", "llama3.2", "qwen2.5", "mistral", "mixtral"]):
                capabilities["tools"] = True

            # Thinking/reasoning capability
            thinking_markers = ["<think>", "<thinking>", "reasoning", "chain-of-thought"]
            if any(marker.lower() in template_lower for marker in thinking_markers):
                capabilities["thinking"] = True
            if any(name in model_lower for name in ["deepseek", "qwq", "o1", "reflection"]):
                capabilities["thinking"] = True

            # Embedding capability
            if "embed" in model_lower or details.get("format") == "embedding":
                capabilities["embedding"] = True

            return {
                "model": model,
                "parameter_size": param_size,
                "family": details.get("family", ""),
                "families": families,
                "quantization": details.get("quantization_level", ""),
                "context_length": context_length,
                "format": details.get("format", ""),
                "capabilities": capabilities,
            }
    except Exception as e:
        return {
            "model": model,
            "error": str(e),
            "parameter_size": None,
            "context_length": None,
            "capabilities": {"vision": False, "tools": False, "thinking": False, "embedding": False},
        }


@register("ollama/set_gpu", needs_db=True)
def handle_set_gpu(db: Database, *, enabled: bool) -> dict[str, Any]:
    """Enable or disable GPU inference."""
    db.set_state(key="ollama_gpu_enabled", value="true" if enabled else "false")
    return {"ok": True, "gpu_enabled": enabled}


@register("ollama/set_context", needs_db=True)
def handle_set_context(db: Database, *, num_ctx: int) -> dict[str, Any]:
    """Set context length for inference."""
    if num_ctx < 512:
        raise RpcError(code=INVALID_PARAMS, message="Context length must be at least 512")
    if num_ctx > 131072:
        raise RpcError(code=INVALID_PARAMS, message="Context length cannot exceed 131072")

    db.set_state(key="ollama_num_ctx", value=str(num_ctx))
    return {"ok": True, "num_ctx": num_ctx}


@register("ollama/pull_start", needs_db=True)
def handle_pull_start(db: Database, *, model: str) -> dict[str, Any]:
    """Start pulling a new Ollama model in background. Returns pull_id for tracking."""
    import uuid
    from reos.settings import settings

    stored_url = db.get_state(key="ollama_url")
    base_url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url
    pull_url = base_url.rstrip("/") + "/api/pull"

    pull_id = str(uuid.uuid4())[:8]

    # Initialize pull state
    with _pull_lock:
        _active_pulls[pull_id] = {
            "model": model,
            "status": "starting",
            "progress": 0,
            "total": 0,
            "completed": 0,
            "error": None,
            "done": False,
        }

    def do_pull() -> None:
        import httpx

        try:
            with httpx.Client(timeout=None) as client:
                # Stream the pull to get progress updates
                with client.stream("POST", pull_url, json={"name": model, "stream": True}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            with _pull_lock:
                                if pull_id not in _active_pulls:
                                    break
                                pull_state = _active_pulls[pull_id]
                                pull_state["status"] = data.get("status", "downloading")

                                # Update progress if available
                                if "total" in data and "completed" in data:
                                    total = data["total"]
                                    completed = data["completed"]
                                    pull_state["total"] = total
                                    pull_state["completed"] = completed
                                    if total > 0:
                                        pull_state["progress"] = int((completed / total) * 100)

                                # Check for completion
                                if data.get("status") == "success":
                                    pull_state["done"] = True
                                    pull_state["progress"] = 100

                                # Check for error
                                if "error" in data:
                                    pull_state["error"] = data["error"]
                                    pull_state["done"] = True
                        except json.JSONDecodeError:
                            continue

            # Mark as done if we exit cleanly
            with _pull_lock:
                if pull_id in _active_pulls:
                    _active_pulls[pull_id]["done"] = True
                    if _active_pulls[pull_id]["progress"] == 0:
                        _active_pulls[pull_id]["progress"] = 100

        except Exception as e:
            with _pull_lock:
                if pull_id in _active_pulls:
                    _active_pulls[pull_id]["error"] = str(e)
                    _active_pulls[pull_id]["done"] = True

    # Start pull in background thread
    thread = threading.Thread(target=do_pull, daemon=True)
    thread.start()

    return {"pull_id": pull_id, "model": model}


@register("ollama/pull_status")
def handle_pull_status(*, pull_id: str) -> dict[str, Any]:
    """Get status of an ongoing pull."""
    with _pull_lock:
        if pull_id not in _active_pulls:
            return {"error": "Pull not found", "done": True}

        state = _active_pulls[pull_id].copy()

        # Clean up completed pulls after reporting
        if state["done"]:
            del _active_pulls[pull_id]

        return state


@register("ollama/pull_model", needs_db=True)
def handle_pull_model(db: Database, *, model: str) -> dict[str, Any]:
    """Legacy: Start pulling a new Ollama model. Use pull_start for progress tracking."""
    result = handle_pull_start(db, model=model)
    return {"ok": True, "message": f"Model '{model}' pull started", "pull_id": result["pull_id"]}


@register("ollama/test_connection", needs_db=True)
def handle_test_connection(db: Database, *, url: str | None = None) -> dict[str, Any]:
    """Test Ollama connection."""
    from reos.ollama import check_ollama
    from reos.settings import settings

    if url is None:
        stored_url = db.get_state(key="ollama_url")
        url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url

    health = check_ollama(url=url)
    return {
        "url": url,
        "reachable": health.reachable,
        "model_count": health.model_count,
        "error": health.error,
    }


@register("ollama/check_installed", needs_db=True)
def handle_check_installed(_db: Database) -> dict[str, Any]:
    """Check if Ollama is installed on the system."""
    from reos.providers import check_ollama_installed, get_ollama_install_command

    return {
        "installed": check_ollama_installed(),
        "install_command": get_ollama_install_command(),
    }
