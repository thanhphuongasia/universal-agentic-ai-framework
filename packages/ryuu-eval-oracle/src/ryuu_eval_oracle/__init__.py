"""ryuu-eval-oracle — generic oracle ground truth generation with human review workflow.

Public API:

    Protocols:
        IOracleStrategy    — implement per domain (CRUD matrix, class diagram, …)
        IInputSource       — fetch raw case input (file, DB, HTTP)
        IProductionTarget  — run production system to get existing output

    Data:
        ReviewSchema       — describes UI layout for a domain (table / graph / tree / timeline)
        OracleFixture      — persisted ground truth fixture

    Implementations:
        FileInputSource    — load case input from YAML/JSON on disk

    Orchestration:
        OracleWorkflow     — fetch → (optional) prod run → generate candidate → persist
"""

from ryuu_eval_oracle.fixture import OracleFixture
from ryuu_eval_oracle.input_sources import FileInputSource
from ryuu_eval_oracle.protocols import (
    IOracleStrategy,
    IInputSource,
    IProductionTarget,
)
from ryuu_eval_oracle.review_schema import ReviewSchema
from ryuu_eval_oracle.workflow import OracleWorkflow

__all__ = [
    "IOracleStrategy",
    "IInputSource",
    "IProductionTarget",
    "ReviewSchema",
    "OracleFixture",
    "FileInputSource",
    "OracleWorkflow",
]
