"""ryuu_eval.http — generic FastAPI router for eval UI integration."""

from ryuu_eval.http.router import RunnerFactory, build_eval_router

__all__ = ["RunnerFactory", "build_eval_router"]
