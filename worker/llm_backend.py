from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import aiohttp

from .ollama_client import embed_text as ollama_embed_text
from .ollama_client import generate_tags as ollama_generate_tags

log = logging.getLogger("channel-mcp-llm-backend")


def _normalize_backend(value: str | None) -> str:
    backend = (value or "").strip().lower()
    if backend in {"ollama", "llm_mcp"}:
        return backend
    return "llm_mcp"


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    text = text.strip()
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        loaded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _extract_text_from_result(result: dict[str, Any]) -> str:
    data = result.get("data")
    if not isinstance(data, dict):
        return ""

    response_text = data.get("response")
    if isinstance(response_text, str) and response_text.strip():
        return response_text

    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content
            content = first.get("text")
            if isinstance(content, str):
                return content

    return ""


def _extract_embedding_from_result(result: dict[str, Any]) -> list[float]:
    data = result.get("data")
    if not isinstance(data, dict):
        return []

    raw = data.get("embedding")
    if not isinstance(raw, list):
        return []

    out: list[float] = []
    for item in raw:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


async def _enqueue_job(
    session: aiohttp.ClientSession,
    base_url: str,
    payload: dict[str, Any],
) -> str:
    url = f"{base_url.rstrip('/')}/v1/llm/request"
    async with session.post(url, json=payload) as resp:
        body = await resp.text()
        if resp.status not in {200, 202}:
            raise RuntimeError(f"llm_mcp enqueue failed status={resp.status} body={body[:280]}")

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("llm_mcp enqueue returned invalid json") from exc

    job_id = data.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("llm_mcp enqueue missing job_id")
    return job_id


async def _wait_job_result(
    session: aiohttp.ClientSession,
    base_url: str,
    job_id: str,
    timeout_sec: int,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1/jobs/{job_id}"
    started = time.monotonic()
    timeout = max(3, timeout_sec)

    while True:
        if time.monotonic() - started > timeout:
            raise RuntimeError(f"llm_mcp job timeout id={job_id} timeout={timeout}s")

        async with session.get(url) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"llm_mcp job read failed status={resp.status} body={body[:280]}")

        try:
            job = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("llm_mcp job returned invalid json") from exc

        status = str(job.get("status") or "").lower()
        if status == "done":
            result = job.get("result")
            if isinstance(result, dict):
                return result
            raise RuntimeError("llm_mcp job done without structured result")
        if status in {"failed", "error", "cancelled", "canceled"}:
            err_text = job.get("error") or "job failed"
            raise RuntimeError(f"llm_mcp job {status}: {err_text}")

        await asyncio.sleep(0.5)


async def _run_llm_task(
    session: aiohttp.ClientSession,
    llm_mcp_base_url: str,
    request_payload: dict[str, Any],
    timeout_sec: int,
) -> dict[str, Any]:
    job_id = await _enqueue_job(session, llm_mcp_base_url, request_payload)
    return await _wait_job_result(session, llm_mcp_base_url, job_id, timeout_sec)


async def generate_tags(
    session: aiohttp.ClientSession,
    base_url: str,
    model: str,
    text: str,
    max_count: int,
    temperature: float = 0.1,
    system_prompt: str | None = None,
    candidates: list[str] | None = None,
    *,
    llm_backend: str = "llm_mcp",
    llm_mcp_base_url: str = "http://llmcore:8080",
    llm_mcp_provider: str = "auto",
    llm_backend_fallback_ollama: bool = True,
    llm_backend_timeout_sec: int = 30,
) -> tuple[list[str], list[str], dict[str, float], dict[str, Any]]:
    backend = _normalize_backend(llm_backend)
    candidates = candidates or []

    if backend == "llm_mcp":
        try:
            provider = llm_mcp_provider if llm_mcp_provider in {"auto", "ollama", "openai", "openrouter"} else "auto"
            prompt_parts = [
                "Верни ТОЛЬКО JSON формата:",
                '{"tags": ["..."], "emoji": ["..."], "code": {"fear":0.0,"greed":0.0,"volatility":0.0,"hype":0.0,"ad":0.0,"regulatory":0.0,"macro":0.0,"rates":0.0,"fx":0.0,"retail":0.0,"institutional":0.0,"momentum":0.0,"mean_reversion":0.0,"earnings":0.0,"buyback":0.0,"mna":0.0,"ai":0.0,"crypto":0.0,"geopolitics":0.0,"sanctions":0.0,"esg":0.0,"insider":0.0,"ipo":0.0,"dividends":0.0,"banking":0.0,"energy":0.0,"metals":0.0,"consumer":0.0,"supply_chain":0.0,"usefulness":0.0}}',
                f"Ограничения: tags <= {max_count}; emoji <= 3.",
            ]
            if candidates:
                uniq = ", ".join(dict.fromkeys(candidates))
                prompt_parts.append(f"Кандидаты: {uniq}")
            prompt_parts.append("Текст:")
            prompt_parts.append(text)
            prompt = "\n\n".join(prompt_parts)

            payload: dict[str, Any] = {
                "task": "chat",
                "provider": provider,
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": 700,
                "priority": 2,
                "source": "channel-mcp",
                "max_attempts": 2,
            }
            if provider in {"auto", "ollama"} and model:
                payload["model"] = model
            if system_prompt:
                payload["options"] = {"system": system_prompt}

            started = time.perf_counter()
            result = await _run_llm_task(
                session=session,
                llm_mcp_base_url=llm_mcp_base_url,
                request_payload=payload,
                timeout_sec=llm_backend_timeout_sec,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

            raw_text = _extract_text_from_result(result)
            parsed = _extract_json(raw_text) or {}

            tags_raw = parsed.get("tags")
            tags = [str(item).strip() for item in tags_raw if isinstance(item, (str, int, float))] if isinstance(tags_raw, list) else []
            tags = [tag for tag in tags if tag]
            if not tags and candidates:
                tags = list(dict.fromkeys(candidates))[:max_count]
            tags = list(dict.fromkeys(tags))[:max_count]

            emoji_raw = parsed.get("emoji")
            emoji = [str(item).strip() for item in emoji_raw if isinstance(item, str)] if isinstance(emoji_raw, list) else []
            emoji = [item for item in emoji if item][:3]

            code: dict[str, float] = {}
            code_raw = parsed.get("code")
            if isinstance(code_raw, dict):
                for key, value in code_raw.items():
                    try:
                        code[str(key)] = float(value)
                    except (TypeError, ValueError):
                        continue

            meta: dict[str, Any] = {
                "backend": "llm_mcp",
                "provider": result.get("provider"),
                "elapsed_ms": elapsed_ms,
            }
            return tags, emoji, code, meta
        except Exception as exc:
            log.warning("llm.backend.tags.llm_mcp_error: %s", exc)
            if not llm_backend_fallback_ollama:
                raise

    tags, emoji, code, meta = await ollama_generate_tags(
        session=session,
        base_url=base_url,
        model=model,
        text=text,
        max_count=max_count,
        temperature=temperature,
        system_prompt=system_prompt,
        candidates=candidates,
    )
    meta["backend"] = "ollama"
    return tags, emoji, code, meta


async def embed_text(
    session: aiohttp.ClientSession,
    base_url: str,
    model: str,
    text: str,
    *,
    llm_backend: str = "llm_mcp",
    llm_mcp_base_url: str = "http://llmcore:8080",
    llm_mcp_provider: str = "auto",
    llm_backend_fallback_ollama: bool = True,
    llm_backend_timeout_sec: int = 30,
) -> list[float]:
    backend = _normalize_backend(llm_backend)

    if backend == "llm_mcp":
        try:
            provider = llm_mcp_provider
            if provider not in {"auto", "ollama"}:
                provider = "auto"

            payload: dict[str, Any] = {
                "task": "embed",
                "provider": provider,
                "prompt": text,
                "priority": 2,
                "source": "channel-mcp",
                "max_attempts": 2,
            }
            if model:
                payload["model"] = model

            result = await _run_llm_task(
                session=session,
                llm_mcp_base_url=llm_mcp_base_url,
                request_payload=payload,
                timeout_sec=llm_backend_timeout_sec,
            )
            embedding = _extract_embedding_from_result(result)
            if embedding:
                return embedding
            raise RuntimeError("llm_mcp embed returned empty embedding")
        except Exception as exc:
            log.warning("llm.backend.embed.llm_mcp_error: %s", exc)
            if not llm_backend_fallback_ollama:
                raise

    return await ollama_embed_text(
        session=session,
        base_url=base_url,
        model=model,
        text=text,
    )
