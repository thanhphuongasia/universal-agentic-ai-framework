# ryuu-messaging-cli

CLI (stdin/stdout) `IChannelAdapter` for the Ryuu messaging stack.

Zero external dependencies — only depends on `ryuu-messaging-core`. Useful as:
- A development harness for testing `IChannelHandler` implementations without booting a real chat platform.
- Proof that the messaging interface is genuinely channel-neutral (not a Telegram-in-disguise).

## Usage

```python
from ryuu_messaging_core import ChannelOrchestrator
from ryuu_messaging_cli import CLIAdapter

orch = ChannelOrchestrator(conversation_manager=cm, handler=my_handler)
orch.register_channel(CLIAdapter())
await orch.start()
```
