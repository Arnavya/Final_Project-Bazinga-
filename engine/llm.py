"""Provider-agnostic LLM client (OpenAI-compatible chat completions over HTTP).

Works with Groq (default) and Ollama with one env var change, using only the
standard library (urllib) — no SDK dependency. The deterministic `stub` provider
is handled by the callers (investigate/judge/learn) via config.USE_STUB, so this
module only implements real HTTP calls.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from engine import config


class LLMError(RuntimeError):
    pass


def _ssl_context() -> ssl.SSLContext:
    """Use certifi's CA bundle if available (fixes the common macOS python.org
    'CERTIFICATE_VERIFY_FAILED' where the system CA store isn't wired in)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


_SSL_CTX = _ssl_context()


def _endpoint() -> str:
    return f"{config.LLM_BASE_URL}/chat/completions"


def _headers() -> Dict[str, str]:
    # A normal User-Agent is required: Groq sits behind Cloudflare, which blocks the
    # default "Python-urllib/..." agent with a 403 (error code 1010).
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; reasoning-engine/1.0)",
    }
    if config.LLM_PROVIDER == "groq" and config.GROQ_API_KEY:
        headers["Authorization"] = f"Bearer {config.GROQ_API_KEY}"
    return headers


def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    json_mode: bool = False,
    temperature: Optional[float] = None,
    max_retries: int = 3,
) -> str:
    """Call the chat-completions endpoint and return the assistant message text."""
    payload: Dict[str, object] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload).encode("utf-8")
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        req = urllib.request.Request(_endpoint(), data=body, headers=_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT, context=_SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            last_err = LLMError(f"HTTP {exc.code}: {detail[:500]}")
            # Retry on rate-limit / transient server errors; fail fast otherwise.
            if exc.code in (429, 500, 502, 503) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise last_err
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            last_err = LLMError(f"{type(exc).__name__}: {exc}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise last_err

    raise LLMError(str(last_err))  # pragma: no cover


def _extract_json(text: str) -> str:
    """Pull the first balanced JSON object out of a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def chat_json(
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> Dict:
    """Chat call that returns parsed JSON (robust to code fences / extra prose)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raw = chat(messages, model=model, json_mode=True, temperature=temperature)
    try:
        return json.loads(_extract_json(raw))
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model did not return valid JSON: {exc}\n---\n{raw[:800]}")
