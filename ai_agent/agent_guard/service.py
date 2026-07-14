from __future__ import annotations

from collections.abc import Callable

from .adjudication_graph import AnalysisCancellationToken, run_adjudication_graph
from .adjudicator import LLMClient
from .config import AgentGuardConfig
from .diff_store import DiffEvidenceError, DiffRef, create_boto3_diff_store, load_diff_text
from .service_types import AgentSessionProcessResult


def process_finished_session_event(
    event: dict,
    *,
    config: AgentGuardConfig,
    llm: LLMClient,
    diff_text_loader: Callable[[DiffRef], str] | None = None,
    cancellation_token: AnalysisCancellationToken | None = None,
) -> AgentSessionProcessResult:
    cancellation_token = cancellation_token or AnalysisCancellationToken()
    cancellation_token.raise_if_cancelled()
    try:
        raw_ref = event["diff_ref"]
        diff_ref = DiffRef(
            storage=raw_ref["storage"],
            uri=raw_ref["uri"],
            sha256=raw_ref["sha256"],
        )
        diff_text = diff_text_loader(diff_ref) if diff_text_loader else _load_diff_text(diff_ref, config)
    except (KeyError, DiffEvidenceError, OSError) as exc:
        return AgentSessionProcessResult(status="evidence_invalid", error=str(exc))

    cancellation_token.raise_if_cancelled()
    return run_adjudication_graph(
        event=event,
        diff_text=diff_text,
        config=config,
        llm=llm,
        cancellation_token=cancellation_token,
    )


def _load_diff_text(diff_ref: DiffRef, config: AgentGuardConfig) -> str:
    if diff_ref.storage == "local":
        return load_diff_text(diff_ref, max_bytes=config.max_diff_read_bytes)
    if diff_ref.storage in {"s3", "minio"}:
        store = create_boto3_diff_store(
            bucket=config.diff_bucket,
            prefix=config.diff_prefix,
            endpoint_url=config.diff_endpoint_url or None,
            access_key_id=config.diff_access_key_id or None,
            secret_access_key=config.diff_secret_access_key or None,
            region_name=config.diff_region or None,
            storage=diff_ref.storage,
        )
        return store.read_text(diff_ref, max_bytes=config.max_diff_read_bytes)
    return load_diff_text(diff_ref, max_bytes=config.max_diff_read_bytes)
