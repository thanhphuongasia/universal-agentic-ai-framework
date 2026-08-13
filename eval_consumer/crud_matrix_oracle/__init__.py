"""CRUD Matrix Oracle — ground truth generation + eval runner."""
from .models import (
    OracleCell,
    OracleFixture,
    RouteMetrics,
    EvalReport,
)

__all__ = ["OracleCell", "OracleFixture", "RouteMetrics", "EvalReport"]
