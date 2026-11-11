"""Small Claude API client: one call, strict JSON out, usage and cost logged.

Needs ANTHROPIC_API_KEY in the environment. Standard library only.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from .config import PRICES
from .db import now

API_URL = "https://api.anthropic.com/v1/messages"


class LLMError(Exception):
    pass


def cost_usd(model, input_tokens, output_tokens):
    pin, pout = PRICES[model]
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


def _post(payload, timeout=60):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(str(e)) from e


def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON in response")
    return json.loads(text[start:])


def call_json(model, system, user, validate, con=None, run_id=None, task=None, max_tokens=1500):
    """Call the model and return (validated_result, stats). Retries once on bad JSON.

    `validate` raises ValueError when the parsed JSON breaks the rules; that error
    text is sent back to the model on the retry.
    """
    messages = [{"role": "user", "content": user}]
    total_in = total_out = 0
    t0 = time.perf_counter()
    last_err = None
    for attempt in range(2):
        resp = _post({"model": model, "max_tokens": max_tokens, "system": system,
                      "messages": messages, "temperature": 0})
        usage = resp.get("usage", {})
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        try:
            result = validate(_extract_json(text))
            last_err = None
            break
        except (ValueError, KeyError, TypeError) as e:
            last_err = str(e)
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"That output was invalid: {last_err}. Reply with corrected JSON only."}]
    stats = {
        "model": model,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": cost_usd(model, total_in, total_out),
        "ok": last_err is None,
        "error": last_err,
    }
    if con is not None:
        con.execute(
            "INSERT INTO ai_calls(run_id, task, model, input_tokens, output_tokens, latency_ms, cost_usd, ok, error, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, task, model, total_in, total_out, stats["latency_ms"], stats["cost_usd"],
             int(stats["ok"]), last_err, now()))
    if last_err:
        raise LLMError(f"invalid output after retry: {last_err}")
    return result, stats
