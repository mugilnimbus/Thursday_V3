"""What the other services send in (service token): the agents' events and the collector's metrics samples."""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from thursday_contracts.events import EventBatch, IngestResult
from thursday_contracts.metrics import MetricsSample

from thursday_gateway.domain.model import InvalidInput
from thursday_gateway.transport.services import Services


def build_ingest_router(s: Services, service_auth: Callable[..., Awaitable[None]]) -> APIRouter:
    r = APIRouter(prefix="/v1", dependencies=[Depends(service_auth)])

    @r.post("/events")
    async def ingest(request: Request) -> IngestResult:
        try:
            batch = EventBatch.model_validate_json(await request.body())
        except ValidationError as exc:
            raise InvalidInput(f"invalid event batch: {exc.error_count()} errors") from exc
        accepted, duplicates, last_seq = s.ingest.accept(batch.events)
        return IngestResult(accepted=accepted, duplicates=duplicates, last_seq=last_seq)  # pyright: ignore[reportArgumentType]

    @r.post("/metrics", status_code=204)
    async def ingest_metrics(request: Request) -> None:
        try:
            sample = MetricsSample.model_validate_json(await request.body())
        except ValidationError as exc:
            raise InvalidInput("invalid metrics sample") from exc
        if s.metrics is not None:
            s.metrics.add(sample)
        s.metrics_hub.publish({"kind": "metrics", "sample": sample.model_dump(mode="json")})

    return r
