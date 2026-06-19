#!/usr/bin/env python3
"""Shared Langfuse helpers for SCRIBE Sentinel eval (spec extraction + post-run fetch)."""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import requests


def is_langfuse_enabled() -> bool:
    return (
        os.environ.get("LANGFUSE_ENABLED", "").strip() == "1"
        and bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))
        and bool(os.environ.get("LANGFUSE_SECRET_KEY"))
    )


def langfuse_host() -> str:
    return os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")


def make_trace_id(run_out_dir: str, task_id: str) -> str:
    seed = f"{run_out_dir}:{task_id}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def langfuse_trace_url(trace_id: str, project_id: str | None = None) -> str:
    host = langfuse_host()
    if project_id:
        return f"{host}/project/{project_id}/traces/{trace_id}"
    return f"{host}/trace/{trace_id}"


def get_langfuse_client():
    """Return a Langfuse client, or None when tracing is disabled.

    Raises RuntimeError when LANGFUSE_ENABLED=1 but the package is missing.
    """
    if not is_langfuse_enabled():
        return None
    try:
        from langfuse import Langfuse
    except ImportError as e:
        raise RuntimeError(
            "LANGFUSE_ENABLED=1 but langfuse package is not installed. "
            "Run: pip install 'langfuse>=3.0.0'"
        ) from e
    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=langfuse_host(),
    )


def trace_spec_extraction(
    *,
    run_out_dir: str,
    task_id: str,
    model: str,
    provider: str,
    question: str,
    input_tokens: int,
    output_tokens: int,
    wall_seconds: float,
    ok: bool,
    error: str | None = None,
) -> dict[str, Any] | None:
    """Create/update the shared per-task trace with a spec-extraction generation."""
    lf = get_langfuse_client()
    if lf is None:
        return None

    trace_id = make_trace_id(run_out_dir, task_id)
    trace = lf.trace(
        id=trace_id,
        name=f"scribe/{task_id}",
        session_id=run_out_dir,
        tags=["scribe", "sentinel_eval", "spec_extraction"],
        metadata={
            "task_id": task_id,
            "run_out_dir": run_out_dir,
            "stage": "spec_extraction",
        },
        input={"task_id": task_id, "question": question[:2000]},
    )
    gen = trace.generation(
        name="spec_extraction",
        model=model,
        input=question[:4000],
        metadata={"provider": provider, "role": "spec_agent"},
    )
    gen.end(
        output={"ok": ok, "error": error},
        usage={
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
        },
        metadata={"wall_seconds": round(wall_seconds, 2)},
    )
    trace.update(
        metadata={
            "spec_extraction_complete": ok,
            "spec_extraction_error": error or "",
        }
    )
    try:
        lf.flush()
    except Exception:
        pass

    return {
        "langfuse_trace_id": trace_id,
        "langfuse_url": langfuse_trace_url(trace_id),
    }


def fetch_langfuse_trace(trace_id: str, retries: int = 3, delay: float = 5.0) -> dict[str, Any] | None:
    """Fetch latency + cost from Langfuse public API (mirrors sentinel-eval-sdk)."""
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "")
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    if not secret or not public or not trace_id:
        return None

    session = requests.Session()
    session.auth = (public, secret)

    for attempt in range(retries):
        try:
            resp = session.get(
                f"{langfuse_host()}/api/public/traces/{trace_id}",
                timeout=15,
            )
            if resp.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(delay)
                continue
            trace = resp.json()
            latency = trace.get("latency")
            cost = trace.get("totalCost")
            project_id = trace.get("projectId")
            if latency is not None and cost is not None:
                return {
                    "trace_id": trace_id,
                    "langfuse_url": langfuse_trace_url(trace_id, project_id),
                    "total_latency_seconds": round(float(latency), 2),
                    "total_cost_usd": round(float(cost), 6),
                    "project_id": project_id,
                }
            if attempt < retries - 1:
                time.sleep(delay)
        except Exception:
            if attempt < retries - 1:
                time.sleep(delay)

    return {
        "trace_id": trace_id,
        "langfuse_url": langfuse_trace_url(trace_id),
        "total_latency_seconds": None,
        "total_cost_usd": None,
        "note": "Trace not yet available in Langfuse. Re-run sentinel_refresh_langfuse_traces.py later.",
    }
