from __future__ import annotations

from ryuu_eval.models import SuiteResult


class GitHubActionsRenderer:
    def render(self, result: SuiteResult) -> str:
        lines: list[str] = []
        if not all(c.passed for c in result.cases):
            lines.append(
                f"::warning::Eval suite '{result.suite_id}': "
                f"{result.passed_count}/{result.total_count} passed ({result.pass_rate:.1%})"
            )
            for cr in result.cases:
                if not cr.passed:
                    msg = cr.error or "; ".join(
                        f"{s.scorer_id}={s.score:.2f}" for s in cr.scores if not s.passed
                    )
                    lines.append(f"::error::Case {cr.case.case_id}: {msg}")
        else:
            lines.append(
                f"::notice::Eval suite '{result.suite_id}': "
                f"all {result.total_count} cases passed"
            )
        return "\n".join(lines)
