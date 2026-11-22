import asyncio
import hashlib
import json
import re
import struct
import zlib
from collections.abc import Sequence
from typing import Any

import numpy as np
from redis.asyncio import Redis

from app.adapters.corpus_version import CorpusVersionStore
from app.core.logging import get_logger
from app.domain.models import DocType

logger = get_logger(__name__)

_WS_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"[?.!\s]+$")
_REDIS_OP_TIMEOUT_S = 0.4


def normalize_query(query: str) -> str:
    """Canonicalize query whitespace, case, and trailing punctuation for L1 exact lookup."""
    collapsed = _WS_RE.sub(" ", query.strip().lower())
    return _TRAILING_PUNCT_RE.sub("", collapsed)


def doc_types_fingerprint(doc_types: Sequence[DocType] | None) -> str:
    if not doc_types:
        return "all"
    canonical = ",".join(sorted(set(doc_types)))
    return hashlib.sha1(canonical.encode()).hexdigest()[:12]


def _pack_semantic_entry(embedding: Sequence[float], payload_json: bytes) -> bytes:
    vec = np.asarray(embedding, dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec = vec / norm
    compressed = zlib.compress(payload_json, level=1)
    return struct.pack("<I", vec.shape[0]) + vec.tobytes() + compressed


def _unpack_semantic_entry(raw: bytes) -> tuple[np.ndarray, bytes] | None:
    if len(raw) < 4:
        return None
    dim = struct.unpack("<I", raw[:4])[0]
    vec_end = 4 + (dim * 4)
    if len(raw) <= vec_end:
        return None
    vec = np.frombuffer(raw[4:vec_end], dtype=np.float32)
    return vec, raw[vec_end:]


class RedisSemanticCache:
    """
    Portable generation-versioned two-tier semantic cache (works identically on Redis 8
    and Upstash Redis Free without requiring RediSearch modules).

    - Generation key: `tenant:version:{tenant_id}` (atomic INCR -> O(1) invalidation)
    - L1 Exact key:   `cache:exact:{tenant_id}:v{ver}:{filter}:{sha256(norm_query)}`
    - L2 Vector key:  `cache:vec:{tenant_id}:v{ver}:{filter}` (capped list + NumPy cosine > 0.95)
    - Fail-open:      Redis timeouts/errors degrade cleanly to cache miss without failing queries.
    """

    def __init__(
        self,
        redis_client: Redis | None,
        *,
        corpus_versions: CorpusVersionStore | None = None,
        similarity_threshold: float = 0.95,
        max_entries: int = 500,
        default_ttl_seconds: int = 86400,
    ) -> None:
        self._redis = redis_client
        self._corpus_versions = corpus_versions or CorpusVersionStore(redis_client)
        self._threshold = similarity_threshold
        self._max_entries = max_entries
        self._default_ttl = default_ttl_seconds

    @staticmethod
    def _exact_key(
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query: str,
    ) -> str:
        filt = doc_types_fingerprint(doc_types)
        q_hash = hashlib.sha256(normalize_query(query).encode()).hexdigest()
        return f"cache:exact:{tenant_id}:v{corpus_version}:{filt}:{q_hash}"

    @staticmethod
    def _vector_key(
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
    ) -> str:
        filt = doc_types_fingerprint(doc_types)
        return f"cache:vec:{tenant_id}:v{corpus_version}:{filt}"

    async def get_corpus_version(self, tenant_id: str) -> int:
        return await self._corpus_versions.get_version(tenant_id)

    async def bump_corpus_version(self, tenant_id: str) -> int:
        return await self._corpus_versions.bump_version(tenant_id)

    async def lookup_exact(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query: str,
    ) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        key = self._exact_key(tenant_id, corpus_version, doc_types, query)
        try:
            async with asyncio.timeout(_REDIS_OP_TIMEOUT_S):
                raw = await self._redis.get(key)
            if not raw:
                return None
            raw_bytes = raw if isinstance(raw, bytes) else str(raw).encode()
            decompressed = zlib.decompress(raw_bytes)
            parsed: dict[str, Any] = json.loads(decompressed)
            return parsed
        except Exception as exc:
            logger.warning("cache_l1_lookup_failed", tenant_id=tenant_id, error=str(exc))
            return None

    async def lookup_semantic(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query_embedding: list[float],
    ) -> tuple[dict[str, Any], float] | None:
        if self._redis is None or not query_embedding:
            return None

        key = self._vector_key(tenant_id, corpus_version, doc_types)
        try:
            async with asyncio.timeout(_REDIS_OP_TIMEOUT_S):
                entries = await self._redis.lrange(key, 0, self._max_entries - 1)  # type: ignore[misc]
            if not entries:
                return None

            query_vec = np.asarray(query_embedding, dtype=np.float32)
            q_norm = float(np.linalg.norm(query_vec))
            if q_norm == 0.0:
                return None
            query_vec = query_vec / q_norm

            vectors: list[np.ndarray] = []
            payloads: list[bytes] = []
            for item in entries:
                raw_bytes = item if isinstance(item, bytes) else str(item).encode()
                unpacked = _unpack_semantic_entry(raw_bytes)
                if unpacked is None:
                    continue
                vec, compressed_payload = unpacked
                if vec.shape[0] != query_vec.shape[0]:
                    continue
                vectors.append(vec)
                payloads.append(compressed_payload)

            if not vectors:
                return None

            matrix = np.vstack(vectors)
            similarities = matrix @ query_vec
            best_idx = int(np.argmax(similarities))
            best_sim = float(similarities[best_idx])

            if best_sim < self._threshold:
                return None

            parsed: dict[str, Any] = json.loads(zlib.decompress(payloads[best_idx]))
            return parsed, round(best_sim, 4)
        except Exception as exc:
            logger.warning("cache_l2_lookup_failed", tenant_id=tenant_id, error=str(exc))
            return None

    async def store(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query: str,
        query_embedding: list[float] | None,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        if self._redis is None:
            return
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        payload_json = json.dumps(payload, separators=(",", ":")).encode()
        exact_key = self._exact_key(tenant_id, corpus_version, doc_types, query)
        compressed_exact = zlib.compress(payload_json, level=1)

        try:
            async with asyncio.timeout(_REDIS_OP_TIMEOUT_S):
                pipe = self._redis.pipeline(transaction=False)
                pipe.set(exact_key, compressed_exact, ex=ttl)
                if query_embedding is not None:
                    vec_key = self._vector_key(tenant_id, corpus_version, doc_types)
                    packed = _pack_semantic_entry(query_embedding, payload_json)
                    pipe.lpush(vec_key, packed)
                    pipe.ltrim(vec_key, 0, self._max_entries - 1)
                    pipe.expire(vec_key, ttl)
                await pipe.execute()
        except Exception as exc:
            logger.warning("cache_store_failed", tenant_id=tenant_id, error=str(exc))
