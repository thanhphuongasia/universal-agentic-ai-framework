"""Pluggable system / host ITools for Ryuu agents.

See README for the plug-in convention. The typical wire-up is:

    from ryuu_system_tools import SystemToolset
    toolset = SystemToolset.from_layered()
    agent = Agent(tools=[*toolset.tools, ...])
"""
from ryuu_system_tools.toolset import SystemToolset

__all__ = ["SystemToolset"]
