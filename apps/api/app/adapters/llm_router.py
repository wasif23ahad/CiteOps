import asyncio
import json
import time
from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.models import GroundedLLMResult, LLMUsedPassage, RerankedChunk
from app.schemas.query import GroundedLLMOutputSchema

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are CiteOps, a strict Tier-2 Support and Security Compliance engine.

MANDATORY GROUNDING RULES:
1. Rely EXCLUSIVELY on the numbered context passages [1]..[N] provided in the user prompt.
   Never use outside parametric memory or assume unstated policies, pricing, or defaults.
2. Cite EVERY factual claim inline using square-bracket markers like [1] or [1][2] matching the
   exact passage numbers provided.
3. For every cited passage number, add an entry to `used_passages` with `passage_index` and a
   short verbatim `supporting_quote` copied word-for-word from that passage.
4. Pay close attention to legal/compliance boundaries (e.g., if a feature is NOT included by
   default and requires an addendum, state that exact conditional boundary clearly with citations).
5. ABSTENTION RULE: If the provided passages do NOT directly contain sufficient evidence to
   answer the user's question (or only mention tangentially related words without answering it),
   you MUST set:
   - `status`: "insufficient_evidence"
   - `answer`: concise explanation that the tenant knowledge base lacks supporting evidence
   - `missing_evidence_reason`: specifically describe what documentation is missing
   - `used_passages`: []
6. Keep answers crisp, technical, and audit-ready. Never invent document IDs or page numbers."""

_THINKING_LEVEL_MAP = {
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}


class LLMUnavailableError(RuntimeError):
    """Raised when all configured LLM providers fail or are rate-limited."""


def _is_transient_capacity_error(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        return exc.code in {429, 500, 502, 503, 504}
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, (TimeoutError, ConnectionError, httpx.TransportError))


def format_grounded_prompt(query: str, passages: Sequence[RerankedChunk]) -> str:
    """Format numbered context passages without raw DB UUIDs or page numbers."""
    blocks: list[str] = []
    for idx, item in enumerate(passages, start=1):
        c = item.chunk
        blocks.append(
            f"[{idx}] Document: {c.doc_title} | Version: {c.version} | "
            f"Type: {c.doc_type} | Section: {c.section_path}\n"
            f"{c.content}"
        )
    context_str = "\n\n---\n\n".join(blocks)
    return (
        f"CONTEXT PASSAGES:\n{context_str}\n\n"
        f"USER QUESTION:\n{query}\n\n"
        "Respond strictly according to the JSON schema and grounding rules."
    )


def _schema_to_domain(parsed: GroundedLLMOutputSchema) -> GroundedLLMResult:
    return GroundedLLMResult(
        status=parsed.status,
        answer=parsed.answer.strip(),
        missing_evidence_reason=(
            parsed.missing_evidence_reason.strip()
            if parsed.missing_evidence_reason
            else None
        ),
        used_passages=tuple(
            LLMUsedPassage(
                passage_index=p.passage_index,
                supporting_quote=p.supporting_quote.strip(),
            )
            for p in parsed.used_passages
        ),
    )


class ResilientLLMRouter:
    """
    Free-tier resilient LLM router with bounded HTTP timeouts and per-model circuit breaker:
      - `gemini`: `gemini-3.8-flash` (thinking=low) -> `gemini-3.5-flash-lite` -> optional Groq
      - `ollama`: local zero-egress privacy endpoint
    """

    def __init__(
        self,
        settings: Settings,
        *,
        cooldown_seconds: float = 300.0,
        request_timeout_ms: int = 8_000,
    ) -> None:
        self._settings = settings
        self._cooldown_seconds = cooldown_seconds
        self._cooldown_until: dict[str, float] = {}
        self._http_client: httpx.AsyncClient | None = None

        # Disable SDK's hidden multi-minute internal retry loop so failover happens quickly
        self._gemini_client: genai.Client | None = (
            genai.Client(
                api_key=settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=request_timeout_ms,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            if settings.gemini_api_key
            else None
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=25.0)
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _is_in_cooldown(self, model_name: str) -> bool:
        return time.monotonic() < self._cooldown_until.get(model_name, 0.0)

    def _trip_circuit(self, model_name: str) -> None:
        self._cooldown_until[model_name] = time.monotonic() + self._cooldown_seconds

    async def generate(
        self,
        *,
        query: str,
        passages: Sequence[RerankedChunk],
    ) -> tuple[GroundedLLMResult, str]:
        if not passages:
            return (
                GroundedLLMResult(
                    status="insufficient_evidence",
                    answer="No relevant documentation passages were retrieved for this query.",
                    missing_evidence_reason="Zero passages available for synthesis.",
                    used_passages=(),
                ),
                "none",
            )

        if self._settings.llm_provider == "ollama":
            result = await self._call_ollama(query, passages)
            return result, f"ollama/{self._settings.ollama_model}"

        errors: list[str] = []

        # 1. Gemini Primary -> Fallback chain with circuit-breaker fast skip
        if self._gemini_client is not None:
            candidates: list[tuple[str, bool]] = [(self._settings.gemini_primary_model, True)]
            if self._settings.gemini_fallback_model != self._settings.gemini_primary_model:
                candidates.append((self._settings.gemini_fallback_model, False))
            # Try non-cooled-down models first; if all are in cooldown, probe them anyway
            ordered = [c for c in candidates if not self._is_in_cooldown(c[0])] or candidates
            for model_name, use_thinking in ordered:
                try:
                    result = await self._call_gemini(
                        model_name=model_name,
                        query=query,
                        passages=passages,
                        use_thinking=use_thinking,
                    )
                    self._cooldown_until.pop(model_name, None)
                    return result, model_name
                except Exception as exc:
                    if _is_transient_capacity_error(exc):
                        self._trip_circuit(model_name)
                    err_msg = f"{model_name}: {type(exc).__name__}({exc})"
                    errors.append(err_msg)
                    logger.warning(
                        "llm_provider_failover",
                        failed_model=model_name,
                        cooldown_s=self._cooldown_seconds
                        if _is_transient_capacity_error(exc)
                        else 0,
                        error=str(exc),
                    )

        # 2. Optional Secondary API Fallback: Groq (context trimmed to top 3 for 8k-12k TPM caps)
        if self._settings.groq_api_key:
            try:
                trimmed = list(passages[:3])
                result = await self._call_groq(query, trimmed)
                return result, f"groq/{self._settings.groq_fallback_model}"
            except Exception as exc:
                err_msg = f"groq/{self._settings.groq_fallback_model}: {type(exc).__name__}({exc})"
                errors.append(err_msg)
                logger.warning("llm_groq_fallback_failed", error=str(exc))

        raise LLMUnavailableError(
            "All configured LLM providers failed or are rate-limited: "
            + "; ".join(errors or ["No API keys configured"])
        )

    def _call_gemini_sync(
        self,
        *,
        model_name: str,
        user_prompt: str,
        use_thinking: bool,
    ) -> GroundedLLMResult:
        if self._gemini_client is None:
            raise LLMUnavailableError("GEMINI_API_KEY is not configured.")

        thinking_cfg = (
            types.ThinkingConfig(
                thinking_level=_THINKING_LEVEL_MAP[self._settings.gemini_thinking_level]
            )
            if use_thinking
            else None
        )

        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=GroundedLLMOutputSchema,
            thinking_config=thinking_cfg,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._gemini_client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=config,
        )
        raw_text = response.text
        if not raw_text:
            raise RuntimeError(f"Empty response returned by {model_name}.")
        parsed = GroundedLLMOutputSchema.model_validate_json(raw_text)
        return _schema_to_domain(parsed)

    async def _call_gemini(
        self,
        *,
        model_name: str,
        query: str,
        passages: Sequence[RerankedChunk],
        use_thinking: bool,
    ) -> GroundedLLMResult:
        prompt = format_grounded_prompt(query, passages)
        return await asyncio.to_thread(
            self._call_gemini_sync,
            model_name=model_name,
            user_prompt=prompt,
            use_thinking=use_thinking,
        )

    async def _call_groq(
        self, query: str, passages: Sequence[RerankedChunk]
    ) -> GroundedLLMResult:
        schema_json = json.dumps(GroundedLLMOutputSchema.model_json_schema())
        system_msg = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Return ONLY valid JSON conforming strictly to this JSON Schema:\n{schema_json}"
        )
        user_prompt = format_grounded_prompt(query, passages)

        client = self._get_http_client()
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            timeout=20.0,
            headers={
                "Authorization": f"Bearer {self._settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._settings.groq_fallback_model,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = GroundedLLMOutputSchema.model_validate_json(content)
        return _schema_to_domain(parsed)

    async def _call_ollama(
        self, query: str, passages: Sequence[RerankedChunk]
    ) -> GroundedLLMResult:
        user_prompt = format_grounded_prompt(query, passages)
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/chat"
        client = self._get_http_client()
        resp = await client.post(
            url,
            timeout=60.0,
            json={
                "model": self._settings.ollama_model,
                "stream": False,
                "format": GroundedLLMOutputSchema.model_json_schema(),
                "options": {"temperature": 0.0},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["message"]["content"]
        parsed = GroundedLLMOutputSchema.model_validate_json(content)
        return _schema_to_domain(parsed)
