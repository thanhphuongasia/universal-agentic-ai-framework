"""ryuu-reasoning — Phase 14.7 formal verifiers for RYUU agents.

Public API:
  - `Rule`, `RuleVerifier` — pure Python rule-based (no deps)
  - `Z3Verifier` — SMT solver (optional dep: `pip install "ryuu-reasoning[z3]"`)

Future (Phase 14.7.x):
  - `PrologVerifier` — multi-step logical rules with backtracking (pyswip)
  - `SouffleVerifier` — pattern analysis at scale (Datalog)

Use case matrix:
  | Need                                  | Use                  |
  |---------------------------------------|----------------------|
  | Predicate rules (field comparisons)   | RuleVerifier         |
  | Arithmetic constraints (LP, ILP)      | Z3Verifier           |
  | Logical chains, knowledge base        | PrologVerifier (future) |
  | Pattern queries over large facts       | SouffleVerifier (future) |
"""

from __future__ import annotations

from ryuu_reasoning.rule_verifier import Rule, RuleVerifier

# Z3Verifier import optional — only succeeds if z3-solver installed
try:
    from ryuu_reasoning.z3_verifier import Z3Verifier
    _HAS_Z3 = True
except ImportError:
    Z3Verifier = None   # type: ignore[assignment,misc]
    _HAS_Z3 = False


__all__ = [
    "Rule",
    "RuleVerifier",
    "Z3Verifier",
]
