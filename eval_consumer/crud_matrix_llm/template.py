"""EvalCaseTemplate for the crud_matrix_llm suite.

Project-specific schema for code-analysis CRUD matrix evals. Lives here
because the input/expected shape, examples, and tags are tied to Java
Spring Boot semantics — not generic.
"""

from __future__ import annotations

from ryuu_eval_core.models import EvalCaseTemplate

TEMPLATE = EvalCaseTemplate(
    template_id="crud_matrix_llm",
    suite_id="crud_matrix_llm",
    title="CRUD Matrix LLM",
    description="Given Java snippets + call graph, output the CRUD cell matrix per entity field.",
    input_schema={
        "type": "object",
        "properties": {
            "template_id": {"type": "string"},
            "title": {"type": "string"},
            "java_snippets": {
                "type": "array",
                "items": {"type": "object", "properties": {"filename": {"type": "string"}, "source": {"type": "string"}}},
            },
            "route": {"type": "object", "description": "endpoint, http_method, entry_method_id"},
            "entities": {"type": "array", "description": "Entity definitions with fields + annotations"},
            "call_subgraph": {"type": "object", "description": "Method call chain from entry point"},
        },
    },
    expected_schema={
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["populated", "empty"]},
            "route_label": {"type": "string", "description": "e.g. 'POST /orders'"},
            "cells": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "entity": {"type": "string"},
                    "column": {"type": "string"},
                    "op": {"type": "string", "enum": ["C", "R", "U", "D"]},
                }},
            },
            "why": {"type": "string"},
        },
    },
    examples=[
        {
            "input": {
                "template_id": "crud_happy_path_v1",
                "title": "Happy path — POST /orders",
                "java_snippets": [{"filename": "Order.java", "source": "@Entity public class Order { @Id Long id; BigDecimal total; String status; }"}],
                "route": {"endpoint": "/orders", "http_method": "POST"},
                "entities": [{"short_name": "Order", "fields": [{"name": "status"}, {"name": "total"}]}],
                "call_subgraph": {"test::OrderController::createOrder::()": [
                    {"from_class": "OrderService", "to_class": "Order", "to_method": "setStatus"},
                    {"from_class": "OrderService", "to_class": "Order", "to_method": "setTotal"},
                ]},
            },
            "expected": {
                "verdict": "populated",
                "route_label": "POST /orders",
                "cells": [
                    {"entity": "Order", "column": "status", "op": "C"},
                    {"entity": "Order", "column": "total", "op": "C"},
                ],
            },
        },
        {
            "input": {
                "template_id": "crud_happy_path_v1",
                "title": "Empty matrix — GET /health",
                "java_snippets": [{"filename": "HealthController.java", "source": "@RestController public class HealthController { @GetMapping('/health') public Map<String,String> health() { return Map.of('status','OK'); } }"}],
                "route": {"endpoint": "/health", "http_method": "GET"},
                "entities": [],
                "call_subgraph": {},
            },
            "expected": {"verdict": "empty", "route_label": "GET /health", "cells": []},
        },
    ],
    tags=["crud", "java", "spring-boot", "code-analysis"],
)
