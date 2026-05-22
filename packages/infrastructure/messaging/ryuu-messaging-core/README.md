# ryuu-messaging-core

Channel-agnostic messaging primitives for the Ryuu framework.

## What's inside

- `IChannelAdapter` — Layer 1 transport contract (one impl per chat platform)
- `IChannelHandler` — Layer 3 product-logic contract
- `IScopeResolver` + `DefaultScopeResolver` + `SingleTenantResolver` — tenant identity
- `Session`, `ISessionStore`, `InMemorySessionStore` — short-term conversation state
- `ConversationManager` — Layer 2 glue (session lookup + scope resolution)
- `ChannelOrchestrator` — persistent process that runs adapters concurrently
- `IncomingMessage`, `OutgoingMessage` — canonical message types

## Zero channel dependencies

This package has NO knowledge of Telegram, Slack, Discord, etc. Install one or more sibling packages (`ryuu-messaging-cli`, `ryuu-messaging-telegram`, …) to connect real chat platforms.

## Usage sketch

```python
from ryuu_messaging_core import (
    ChannelOrchestrator, ConversationManager,
    DefaultScopeResolver, InMemorySessionStore,
)
from ryuu_messaging_cli import CLIAdapter

cm = ConversationManager(
    session_store=InMemorySessionStore(),
    scope_resolver=DefaultScopeResolver(),
)
orch = ChannelOrchestrator(conversation_manager=cm, handler=MyHandler())
orch.register_channel(CLIAdapter())
await orch.start()
```

See `examples/ryuu_sensei/` in the framework repo for a full demo with Telegram + tool-calling.
