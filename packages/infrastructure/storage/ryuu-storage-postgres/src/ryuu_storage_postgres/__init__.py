from ryuu_storage_core import ProfileEntry  # canonical home — re-exported for convenience
from ryuu_storage_postgres._pool import close_all
from ryuu_storage_postgres.collection import PostgresCollectionStore
from ryuu_storage_postgres.handler_state import HandlerState, PostgresHandlerStateStore
from ryuu_storage_postgres.eval_run_store import PostgresEvalRunStore
from ryuu_storage_postgres.kv import PostgresKVStore
from ryuu_storage_postgres.profile import PostgresProfileStore
from ryuu_storage_postgres.prompt_store import PostgresPromptStore
from ryuu_storage_postgres.session import PostgresSessionStore
from ryuu_storage_postgres.suite_store import PostgresSuiteStore
from ryuu_storage_postgres.test_case_store import PostgresTestCaseStore

__all__ = [
    # legacy blob stores (IKVStore / ICollectionStore)
    "PostgresKVStore",
    "PostgresCollectionStore",
    # normalized stores
    "PostgresSessionStore",
    "PostgresHandlerStateStore",
    "HandlerState",
    "PostgresProfileStore",
    "ProfileEntry",   # from ryuu_storage_core — canonical, not duplicated
    # prompt lifecycle store (IPromptStore → ryuu_prompts)
    "PostgresPromptStore",
    # eval schema stores (ISuiteStore / ITestCaseStore / IEvalRunStore → ryuu_eval_core)
    "PostgresSuiteStore",
    "PostgresTestCaseStore",
    "PostgresEvalRunStore",
    # pool lifecycle
    "close_all",
]
