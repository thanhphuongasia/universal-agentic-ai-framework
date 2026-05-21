# ryuu-reasoning

Formal verifiers for RYUU agents. Pure Python rule verifier + optional Z3 SMT backend.

```python
from ryuu_reasoning import RuleVerifier, Rule
# Z3 optional: pip install "ryuu-reasoning[z3]"
from ryuu_reasoning import Z3Verifier  # requires z3-solver
```
