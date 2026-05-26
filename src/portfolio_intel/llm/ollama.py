"""Thin Ollama client.

Uses stdlib urllib so we don't add another dependency. The local Ollama
server speaks HTTP on 11434 by default. We hit /api/generate with
stream=false to get a single response.

Default model is configurable via OLLAMA_MODEL env var (CLAUDE.md says
"make the model name a config variable").
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")


class OllamaError(RuntimeError):
    """Raised when the Ollama server cannot fulfill a request."""


@dataclass(frozen=True)
class OllamaResponse:
    text: str
    model: str
    eval_count: int | None
    duration_ms: int | None


def generate(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    temperature: float = 0.3,
    timeout: float = 120.0,
) -> OllamaResponse:
    """Call Ollama's /api/generate with stream=false."""
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        body["system"] = system

    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
        raise OllamaError(f"Ollama HTTP {e.code}: {body_text}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise OllamaError(
            f"cannot reach Ollama at {host} — is `ollama serve` running? ({e})"
        ) from e
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama returned non-JSON: {e}") from e

    text = (payload.get("response") or "").strip()
    if not text:
        raise OllamaError(f"Ollama returned empty response: {payload}")

    duration_ns = payload.get("total_duration")
    return OllamaResponse(
        text=text,
        model=payload.get("model", model),
        eval_count=payload.get("eval_count"),
        duration_ms=int(duration_ns / 1_000_000) if isinstance(duration_ns, int) else None,
    )
