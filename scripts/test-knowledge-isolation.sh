#!/usr/bin/env bash
# Verify ryuu-knowledge-* packages are independently installable without the full ryuu package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$(mktemp -d)/venv-knowledge-isolation"

echo "=== knowledge-isolation: creating fresh venv at $VENV_DIR ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== knowledge-isolation: installing ryuu-knowledge-* packages (editable) ==="
pip install -e "$REPO_ROOT/packages/ryuu-knowledge-base" -q
pip install -e "$REPO_ROOT/packages/ryuu-knowledge-memory" -q
pip install -e "$REPO_ROOT/packages/ryuu-knowledge-graph" -q
pip install -e "$REPO_ROOT/packages/ryuu-knowledge" -q

echo "=== knowledge-isolation: verifying ryuu is NOT installed ==="
python3 -c "
import sys
try:
    import ryuu
    print('FAIL: ryuu imported — it should not be present', file=sys.stderr)
    sys.exit(1)
except ModuleNotFoundError:
    print('OK: import ryuu → ModuleNotFoundError (expected)')
"

echo "=== knowledge-isolation: smoke test ryuu_knowledge_base ==="
python3 -c "
from ryuu_knowledge_base.backbone import AssembledContext, BackboneType, IKnowledgeBackbone, QueryResult
from ryuu_knowledge_base.context_assembler import ContextAssembler

assert BackboneType.MEMORY == 'memory'
assert BackboneType.GRAPH == 'graph'
assert BackboneType.HYBRID == 'hybrid'
r = QueryResult(results=['a'], scores=[0.9])
assert r.results == ['a']
print('OK: ryuu_knowledge_base smoke test passed')
"

echo "=== knowledge-isolation: smoke test ryuu_knowledge_memory ==="
python3 -c "
import asyncio
from ryuu_knowledge_memory.store import MemoryEntry, MemoryLayer
from ryuu_knowledge_memory.working import WorkingMemoryStore
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
from ryuu_knowledge_memory.backbone import MemoryBackbone

async def test():
    b = MemoryBackbone()
    await b.write('hello world', 'scope1')
    result = await b.query('hello', 'scope1', top_k=5)
    assert len(result.results) >= 1
    print('OK: ryuu_knowledge_memory smoke test passed')

asyncio.run(test())
"

echo "=== knowledge-isolation: smoke test ryuu_knowledge_graph ==="
python3 -c "
import asyncio
from ryuu_knowledge_graph.store import Edge, IGraphStore, Node
from ryuu_knowledge_graph.in_memory import InMemoryGraphStore
from ryuu_knowledge_graph.backbone import GraphBackbone

async def test():
    b = GraphBackbone()
    await b.write('graph node content', 'scope1')
    result = await b.query('graph', 'scope1', top_k=5)
    assert 'graph node content' in result.results
    print('OK: ryuu_knowledge_graph smoke test passed')

asyncio.run(test())
"

echo "=== knowledge-isolation: smoke test ryuu_knowledge (hybrid) ==="
python3 -c "
import asyncio
from ryuu_knowledge.hybrid import HybridBackbone
from ryuu_knowledge_base.backbone import BackboneType

async def test():
    h = HybridBackbone()
    assert h.backbone_type == BackboneType.HYBRID
    await h.write('hybrid test observation', 'scope1')
    result = await h.query('hybrid', 'scope1', top_k=5)
    assert any('hybrid' in r for r in result.results)
    print('OK: ryuu_knowledge (hybrid) smoke test passed')

asyncio.run(test())
"

deactivate
rm -rf "$VENV_DIR"
echo "=== knowledge-isolation: PASSED ==="
