"""Back-compat shim package. Canonical: ``ryuu_eval_core.renderers``."""
from ryuu_eval.renderers.api import ApiRenderer
from ryuu_eval.renderers.github_actions import GitHubActionsRenderer
from ryuu_eval.renderers.terminal import TerminalRenderer

__all__ = ["ApiRenderer", "GitHubActionsRenderer", "TerminalRenderer"]
