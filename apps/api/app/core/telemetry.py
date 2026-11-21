from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from langfuse import Langfuse, is_langfuse_span, propagate_attributes

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ObservationKind = Literal["span", "embedding", "retriever", "generation", "guardrail"]


class _NoOpObservation:
    """Lightweight zero-overhead span handle when Langfuse credentials are not configured."""

    def update(self, **kwargs: Any) -> None:
        return None


class TelemetryTracer:
    """
    OpenTelemetry-native Langfuse v3/v4 tracer wrapper.

    - Uses `should_export_span=is_langfuse_span` to drop noisy ASGI/infra spans and
      preserve Langfuse Cloud Hobby's 50,000 monthly tracing units.
    - Degrades cleanly to zero-overhead no-op spans when Langfuse keys are unset or in tests.
    """

    def __init__(self, settings: Settings) -> None:
        self._client: Langfuse | None = None
        if (
            settings.app_env != "test"
            and settings.langfuse_public_key
            and settings.langfuse_secret_key
        ):
            try:
                self._client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    base_url=settings.langfuse_host,
                    environment=settings.app_env,
                    should_export_span=is_langfuse_span,
                )
                logger.info("langfuse_telemetry_enabled", host=settings.langfuse_host)
            except Exception as exc:
                logger.warning("langfuse_init_failed", error=str(exc))
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def trace_query(
        self,
        *,
        tenant_id: str,
        request_id: str,
        query: str,
    ) -> Iterator[tuple[Any, str]]:
        """Open a root query trace and yield `(root_observation, trace_id)`."""
        if self._client is None:
            yield _NoOpObservation(), request_id
            return

        try:
            with propagate_attributes(
                user_id=tenant_id,
                tags=["citeops", "query", f"tenant:{tenant_id}"],
                metadata={"request_id": request_id, "tenant_id": tenant_id},
            ):
                with self._client.start_as_current_observation(
                    name="citeops.query",
                    as_type="span",
                    input={"tenant_id": tenant_id, "query": query},
                    metadata={"request_id": request_id},
                ) as root:
                    trace_id = getattr(root, "trace_id", None) or request_id
                    yield root, str(trace_id)
        except Exception as exc:
            logger.warning("langfuse_trace_error", error=str(exc))
            yield _NoOpObservation(), request_id

    @contextmanager
    def span(
        self,
        name: str,
        *,
        as_type: ObservationKind = "span",
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[Any]:
        """Open a child observation nested under the active OpenTelemetry trace context."""
        if self._client is None:
            yield _NoOpObservation()
            return

        try:
            with self._client.start_as_current_observation(
                name=name,
                as_type=as_type,  # type: ignore[arg-type]
                input=input_data,
                metadata=metadata,
                model=model,
            ) as obs:
                yield obs
        except Exception as exc:
            logger.warning("langfuse_span_error", span_name=name, error=str(exc))
            yield _NoOpObservation()

    def shutdown(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
                self._client.shutdown()
            except Exception as exc:
                logger.warning("langfuse_shutdown_warning", error=str(exc))
