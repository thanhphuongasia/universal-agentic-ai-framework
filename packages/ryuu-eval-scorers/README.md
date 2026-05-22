# ryuu-eval-scorers

Built-in scorer implementations for the Ryuu eval framework. Each scorer satisfies the `Scorer` Protocol from `ryuu-eval-core`.

```python
from ryuu_eval_scorers import ExactMatch, LLMJudgeScorer
from ryuu_eval_core import EvalRunner

scorers = [ExactMatch(), LLMJudgeScorer(provider=my_provider)]
runner = EvalRunner(scorers=scorers, target=my_target)
```
