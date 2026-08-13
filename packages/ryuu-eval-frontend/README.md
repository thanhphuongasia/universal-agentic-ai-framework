# ryuu-eval-frontend (DEPRECATED)

> **This package is deprecated.** Use [`ryuu-eval-ui`](../ryuu-eval-ui/README.md) instead.

This is a backward-compatibility meta-package. It depends on `ryuu-eval-ui`
and re-exports `dist_dir` so existing installations continue to work for one
release cycle.

## Migration

```bash
pip uninstall ryuu-eval-frontend
pip install ryuu-eval-ui
```

Change any imports:
```python
# Before
from ryuu_eval_frontend import dist_dir

# After
from ryuu_eval_ui import dist_dir
```
