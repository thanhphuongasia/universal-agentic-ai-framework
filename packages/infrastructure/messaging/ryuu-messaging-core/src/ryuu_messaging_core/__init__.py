"""Ryuu messaging core — channel-agnostic primitives.

Public API (re-exported from this module):

    from ryuu_messaging_core import (
        # Messages (Layer 1 ↔ 2 boundary types)
        IncomingMessage, OutgoingMessage, Action, Attachment,

        # Protocols (contracts that get implemented by adapters / handlers)
        IChannelAdapter, IChannelHandler, IScopeResolver,
        OnMessageHandler,

        # Session value types
        Session, Turn,

        # Session storage
        ISessionStore, InMemorySessionStore,

        # Scope resolution
        DefaultScopeResolver, SingleTenantResolver,

        # Glue
        ConversationManager, ChannelOrchestrator,
    )

See README.md for usage.
"""

from ryuu_messaging_core.conversation import ConversationManager
from ryuu_messaging_core.dispatcher import (
    CancelToken,
    ClassifyResult,
    DispatchLabel,
    MessageClassifier,
    ScopeDispatcher,
    ScopeState,
    SteeringContext,
)
from ryuu_messaging_core.event_logger import (
    DispatchEvent,
    ErrorEvent,
    IDispatchLogger,
    MessageEvent,
    NullDispatchLogger,
    StandardDispatchLogger,
    TaskEvent,
)
from ryuu_messaging_core.messages import (
    Action,
    Attachment,
    IncomingMessage,
    OutgoingMessage,
)
from ryuu_messaging_core.orchestrator import ChannelOrchestrator
from ryuu_messaging_core.protocols import (
    IChannelAdapter,
    IChannelHandler,
    IScopeResolver,
    OnMessageHandler,
    Session,
    Turn,
)
from ryuu_messaging_core.scope import DefaultScopeResolver, SingleTenantResolver
from ryuu_messaging_core.session import (
    ISessionStore,
    InMemorySessionStore,
    KVSessionStore,
)

__version__ = "0.3.0a2"

__all__ = [
    "Action",
    "Attachment",
    "CancelToken",
    "ChannelOrchestrator",
    "ClassifyResult",
    "ConversationManager",
    "DefaultScopeResolver",
    "DispatchEvent",
    "DispatchLabel",
    "ErrorEvent",
    "IChannelAdapter",
    "IChannelHandler",
    "IDispatchLogger",
    "IScopeResolver",
    "ISessionStore",
    "InMemorySessionStore",
    "KVSessionStore",
    "IncomingMessage",
    "MessageClassifier",
    "MessageEvent",
    "NullDispatchLogger",
    "OnMessageHandler",
    "OutgoingMessage",
    "ScopeDispatcher",
    "ScopeState",
    "Session",
    "SingleTenantResolver",
    "StandardDispatchLogger",
    "SteeringContext",
    "TaskEvent",
    "Turn",
]
