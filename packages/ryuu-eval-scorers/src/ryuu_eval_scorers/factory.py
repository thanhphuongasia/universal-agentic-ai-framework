"""build_scorers — dựng ``list[Scorer]`` từ một scoring spec (JSONB).

Spec là JSON lưu ở ``test_cases.scoring`` (xem docs/eval-prompt-store-schema.md)::

    {
      "scorers": [
        {"type": "contains",  "config": {"required": ["CREATE", "READ"]}},
        {"type": "llm-judge", "config": {"criteria": "factuality"}}
      ],
      "combine":   "and",          # optional: "and"/"all" | "or"/"any"
      "forbidden": ["GraphQL"]     # optional: substring KHÔNG được xuất hiện
    }

Quy ước trả về:

* Mỗi entry trong ``scorers`` → 1 Scorer qua ``_BUILDERS`` (registry pattern —
  thêm scorer mới = thêm 1 dòng, không sửa logic).
* ``combine`` (nếu có) bọc các scorer chính vào 1 ``Composite`` (AND/OR).
* ``forbidden`` LUÔN là gate cứng (AND), kể cả khi ``combine="or"`` — nếu không,
  một OR có thể bỏ qua ràng buộc cấm. Vì vậy nó được thêm *ngoài* Composite.

Chỉ build các scorer biểu diễn được bằng JSON. ``Constraint`` / ``Threshold`` cần
Python callable → dựng bằng code, không qua spec. ``llm-judge`` /
``semantic-similarity`` cần ``provider``; ``structured`` cần ``normalizers`` theo tên.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ryuu_eval_scorers.scorers import (
    Composite,
    Constraint,
    Contains,
    ExactMatch,
    LLMJudge,
    Regex,
    SemanticSimilarity,
    StructuredScorer,
)


# ---------------------------------------------------------------------------
# Build context — mang các phụ thuộc không-serialize-được (provider, normalizers)
# ---------------------------------------------------------------------------


@dataclass
class _BuildContext:
    provider: Any | None = None
    normalizers: dict[str, Callable[[str], str]] = field(default_factory=dict)

    def require_provider(self, type_name: str) -> Any:
        if self.provider is None:
            raise ValueError(
                f"scorer {type_name!r} cần một LLM provider; "
                f"gọi build_scorers(spec, provider=...)"
            )
        return self.provider

    def normalizer(self, name: str | None) -> Callable[[str], str] | None:
        if name is None:
            return None
        if name not in self.normalizers:
            raise ValueError(
                f"normalizer {name!r} chưa đăng ký; "
                f"gọi build_scorers(spec, normalizers={{{name!r}: fn}}). "
                f"Đã có: {sorted(self.normalizers)}"
            )
        return self.normalizers[name]


# ---------------------------------------------------------------------------
# Registry: type → builder(config, ctx) -> Scorer
# Thêm scorer mới biểu diễn-được-bằng-JSON = thêm 1 entry dưới đây.
# ---------------------------------------------------------------------------

_BUILDERS: dict[str, Callable[[dict, _BuildContext], Any]] = {
    "exact-match": lambda c, ctx: ExactMatch(),
    "contains": lambda c, ctx: Contains(
        c["required"],
        case_sensitive=c.get("case_sensitive", False),
        scorer_id=c.get("scorer_id", "contains"),
    ),
    "regex": lambda c, ctx: Regex(
        c["pattern"],
        mode=c.get("mode", "search"),
        scorer_id=c.get("scorer_id", "regex"),
    ),
    "llm-judge": lambda c, ctx: LLMJudge(
        ctx.require_provider("llm-judge"),
        criteria=c.get("criteria", "factuality"),
        threshold=c.get("threshold", 0.7),
        model=c.get("model", ""),
        prompt_template=c.get("prompt_template"),
        aggregate=c.get("aggregate", "avg"),
        scorer_id=c.get("scorer_id", ""),
    ),
    "semantic-similarity": lambda c, ctx: SemanticSimilarity(
        ctx.require_provider("semantic-similarity"),
        threshold=c.get("threshold", 0.7),
        model=c.get("model", ""),
    ),
    "structured": lambda c, ctx: StructuredScorer(
        threshold=c.get("threshold", 0.85),
        key_normalizer=ctx.normalizer(c.get("key_normalizer")),
        value_normalizer=ctx.normalizer(c.get("value_normalizer")),
        valid_vocab=c.get("valid_vocab"),
        scorer_id=c.get("scorer_id", "structured"),
    ),
}


def _norm_type(raw: str) -> str:
    """Chuẩn hoá tên type: 'LLM_Judge' / 'llm_judge' → 'llm-judge'."""
    return raw.strip().lower().replace("_", "-")


def _normalize_combine(combine: str) -> bool:
    """'and'/'all' → require_all=True; 'or'/'any' → False."""
    c = combine.strip().lower()
    if c in ("and", "all"):
        return True
    if c in ("or", "any"):
        return False
    raise ValueError(f"'combine' phải là 'and'/'all' hoặc 'or'/'any', nhận {combine!r}")


def _build_forbidden(forbidden: str | list[str], *, case_sensitive: bool = False) -> Constraint:
    """Constraint phủ định: pass khi KHÔNG có substring cấm nào trong output."""
    needles = [forbidden] if isinstance(forbidden, str) else list(forbidden)

    def _check(output: str, _case: Any) -> bool:
        hay = output if case_sensitive else output.lower()
        return not any((n if case_sensitive else n.lower()) in hay for n in needles)

    return Constraint("forbidden", _check)


def build_scorers(
    spec: dict[str, Any],
    *,
    provider: Any | None = None,
    normalizers: dict[str, Callable[[str], str]] | None = None,
) -> list[Any]:
    """Dựng ``list[Scorer]`` từ một scoring spec (JSONB).

    Args:
        spec:        Dict scoring (xem docstring module).
        provider:    ILLMProvider — bắt buộc nếu spec dùng llm-judge/semantic-similarity.
        normalizers: Map tên → callable cho ``structured`` (key/value normalizer).

    Returns:
        Danh sách Scorer. Consumer (EvalRunner) AND toàn bộ list. Khi ``combine``
        có giá trị, các scorer chính được gộp thành 1 ``Composite``; ``forbidden``
        (nếu có) luôn là phần tử AND riêng — gate cứng.

    Raises:
        TypeError:  spec không phải dict.
        ValueError: type không nhận diện được, list rỗng, thiếu provider/normalizer,
                    hoặc 'combine' không hợp lệ.
    """
    if not isinstance(spec, dict):
        raise TypeError(f"scoring spec phải là dict, nhận {type(spec).__name__}")

    ctx = _BuildContext(provider=provider, normalizers=normalizers or {})

    scorers: list[Any] = []
    for entry in spec.get("scorers", []):
        type_name = _norm_type(entry["type"])
        if type_name not in _BUILDERS:
            raise ValueError(
                f"scorer type không nhận diện được: {entry['type']!r}. "
                f"Đã hỗ trợ: {sorted(_BUILDERS)}"
            )
        scorers.append(_BUILDERS[type_name](entry.get("config", {}), ctx))

    if not scorers:
        raise ValueError("scoring spec không tạo ra scorer nào: 'scorers' rỗng")

    combine = spec.get("combine")
    if combine is not None:
        scorers = [Composite("composite", scorers, require_all=_normalize_combine(combine))]

    forbidden = spec.get("forbidden")
    if forbidden:
        scorers.append(_build_forbidden(forbidden))

    return scorers


def metadata_scorer_resolver(
    *,
    provider: Any | None = None,
    normalizers: dict[str, Callable[[str], str]] | None = None,
    key: str = "scoring",
) -> Callable[[Any], list[Any] | None]:
    """Build a per-case scorer resolver for ``EvalRunner(scorer_for=...)``.

    Returns a callback ``(case) -> list[Scorer] | None`` that reads the scoring
    spec from ``case.metadata[key]`` and runs :func:`build_scorers`. Returns
    None when the case carries no spec (so EvalRunner falls back to its
    suite-level scorers).

    This is the generic bridge between a per-case scoring spec (e.g. the
    ``test_cases.scoring`` JSONB column, surfaced as ``case.metadata['scoring']``)
    and the scorer instances — no per-project glue needed.
    """

    def _resolve(case: Any) -> list[Any] | None:
        meta = getattr(case, "metadata", None) or {}
        spec = meta.get(key)
        if not spec:
            return None
        return build_scorers(spec, provider=provider, normalizers=normalizers)

    return _resolve
