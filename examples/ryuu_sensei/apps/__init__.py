"""Domain apps the sensei can drive.

Each app contributes a set of tools (plain Python functions with type hints)
that `ryuu.Agent` auto-converts to LLM tool schemas. The sensei delegates the
ReAct loop to ryuu.Agent, so apps only own:
  • the tool functions
  • a (per-user) data store
  • an optional sensei subclass that wires user-scoping into the tool layer
"""
