from __future__ import annotations

from ryuu_eval.models import SuiteResult


class TerminalRenderer:
    def render(self, result: SuiteResult) -> str:
        lines = [
            f"Suite: {result.suite_id}",
            f"Pass: {result.passed_count}/{result.total_count} ({result.pass_rate:.1%})",
            f"Cost: ${result.total_cost_usd:.4f}",
            "",
        ]
        for cr in result.cases:
            status = "✓" if cr.passed else "✗"
            lines.append(f"  {status} {cr.case.case_id}")
            if cr.error:
                lines.append(f"    ERROR: {cr.error}")
            for s in cr.scores:
                lines.append(f"    [{s.scorer_id}] score={s.score:.2f} passed={s.passed}")
        return "\n".join(lines)
