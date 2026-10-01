"""Published contracts must not change by accident.

Each model's JSON Schema is compared with a committed snapshot in `contracts/schemas/`.
After an intended, versioned change, regenerate with `THURSDAY_UPDATE_SCHEMAS=1`.
"""

import json
import os
import pathlib

import pytest
from pydantic import BaseModel
from thursday_contracts.approvals import ApprovalAnswer, ApprovalRequest
from thursday_contracts.events import EventBatch, EventEnvelope, IngestResult
from thursday_contracts.health import HealthReport, ReadinessReport
from thursday_contracts.metrics import MetricsSample
from thursday_contracts.problems import Problem
from thursday_contracts.task_control import TaskControlParams, TaskControlResult

SCHEMAS = pathlib.Path(__file__).parents[1] / "schemas"
MODELS: list[type[BaseModel]] = [
    EventEnvelope,
    EventBatch,
    IngestResult,
    HealthReport,
    ReadinessReport,
    ApprovalRequest,
    ApprovalAnswer,
    Problem,
    TaskControlParams,
    TaskControlResult,
    MetricsSample,
]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_schema_matches_snapshot(model: type[BaseModel]) -> None:
    current = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
    path = SCHEMAS / f"{model.__name__}.json"
    if os.environ.get("THURSDAY_UPDATE_SCHEMAS") == "1":
        SCHEMAS.mkdir(exist_ok=True)
        path.write_text(current, encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with THURSDAY_UPDATE_SCHEMAS=1"
    assert path.read_text(encoding="utf-8") == current, (
        f"{model.__name__} schema changed; version it and update the snapshot"
    )
