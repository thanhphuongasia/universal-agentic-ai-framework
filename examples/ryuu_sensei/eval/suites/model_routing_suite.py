"""Model routing heuristic suite cho ryuu_sensei — chạy từ repo root:

    python -m examples.ryuu_sensei.eval.suites.model_routing_suite

Dùng lại RoutingTarget từ framework. Fixtures thuần heuristic (không tốn LLM)
đã chuyển về eval_consumer/cognitive/adaptive_routing/ — chạy thẳng suite framework:

    python -m eval_consumer.cognitive.adaptive_routing.suites.routing_suite

File này chỉ còn là entry point tiện lợi — delegate về framework suite.
"""

from eval_consumer.cognitive.adaptive_routing.suites.routing_suite import main  # noqa: F401

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
