# Backward-compat shim — canonical source is ryuu_knowledge_graph.store
from ryuu_knowledge_graph.store import (  # noqa: F401
    Edge as Edge,
    IGraphStore as IGraphStore,
    Node as Node,
)
