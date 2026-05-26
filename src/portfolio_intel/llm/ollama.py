"""Thin Ollama client.

Uses stdlib urllib so we don't add another dependency. The local Ollama
server speaks HTTP on 11434 by default. Supports both buffered (`generate`)
and streamed (`generate_stream`) calls — streaming is what makes CPU
inference feel usable.

Default model is configurable via OLLAMA_MODEL env var (CLAUDE.md says
"make the model name a config variable").
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator


DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

# Cap output size — the synthesis paragraph is short (4-7 sentences). Without
# this, CPU runs can wander for minutes.
DEFAULT_NUM_PREDICT = 320

# Keep the model in memory between calls so the second `pintel digest` is
# fast. "30m" matches Ollama's own default but is set explicitly so we don't
# rely on server config.
DEFAULT_KEEP_ALIVE = "30m"


class OllamaError(RuntimeError):
    """Raised when the Ollama server cannot fulfill a request."""


@dataclass(frozen=True)
class OllamaResponse:
    text: str
    model: str
    eval_count: int | None
    duration_ms: int | None


def _build_body(
    prompt: str,
    system: str | None,
    model: str,
    temperature: float,
    num_predict: int,
    keep_alive: str,
    stream: bool,
) -> bytes:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "keep_alive": keep_alive,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }
    if system:
        body["system"] = system
    return json.dumps(body).encode("utf-8")


def _open(host: str, body: bytes, timeout: float):
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
        raise OllamaError(f"Ollama HTTP {e.code}: {body_text}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise OllamaError(
            f"cannot reach Ollama at {host} — is `ollama serve` running? ({e})"
        ) from e


def generate(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    temperature: float = 0.3,
    num_predict: int = DEFAULT_NUM_PREDICT,
    keep_alive: str = DEFAULT_KEEP_ALIVE,
    timeout: float = 300.0,
    on_token: Callable[[str], None] | None = None,
) -> OllamaResponse:
    """Generate with streaming under the hood.

    If `on_token` is provided, it is called with each chunk as it arrives,
    making CPU latency visible to the user. The full text is also returned
    so the caller can store / log it. The HTTP timeout is the time between
    bytes — it does NOT cap total generation time.
    """
    body = _build_body(prompt, system, model, temperature, num_predict, keep_alive, stream=True)
    pieces: list[str] = []
    final_payload: dict | None = None

    with _open(host, body, timeout) as r:
        for line in r:
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk = obj.get("response", "")
            if chunk:
                pieces.append(chunk)
                if on_token is not None:
                    on_token(chunk)
            if obj.get("done"):
                final_payload = obj
                break

    text = "".join(pieces).strip()
    if not text:
        raise OllamaError(f"Ollama returned empty response: {final_payload}")

    duration_ns = (final_payload or {}).get("total_duration")
    return OllamaResponse(
        text=text,
        model=(final_payload or {}).get("model", model),
        eval_count=(final_payload or {}).get("eval_count"),
        duration_ms=int(duration_ns / 1_000_000) if isinstance(duration_ns, int) else None,
    )


def generate_stream(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    temperature: float = 0.3,
    num_predict: int = DEFAULT_NUM_PREDICT,
    keep_alive: str = DEFAULT_KEEP_ALIVE,
    timeout: float = 300.0,
) -> Iterator[str]:
    """Yield response chunks as they arrive. Useful when the caller wants to
    do its own streaming without an on_token callback."""
    body = _build_body(prompt, system, model, temperature, num_predict, keep_alive, stream=True)
    with _open(host, body, timeout) as r:
        for line in r:
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk = obj.get("response", "")
            if chunk:
                yield chunk
            if obj.get("done"):
                return
