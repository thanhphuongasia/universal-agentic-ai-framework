# Backward-compat shim — canonical source is ryuu_knowledge_base.backbone
from ryuu_knowledge_base.backbone import (  # noqa: F401
    AssembledContext as AssembledContext,
    BackboneType as BackboneType,
    IKnowledgeBackbone as IKnowledgeBackbone,
    QueryResult as QueryResult,
)
