# ryuu-messaging-telegram

Telegram `IChannelAdapter` for the Ryuu messaging stack, built on `aiogram` v3.

## Features

- Polling mode (dev / hobby deployments)
- `/start`, `/help`, `/clear`, `/settings`, `/verbose`, `/model`, `/status` command handlers (callbacks wired by your product)
- Inline keyboard for `/model` switching (callback_query handler)
- Typing indicator + error trap (LLM/tool errors → friendly user message)
- Plain-text replies (avoids MarkdownV2 escaping minefield)

## Usage

```python
import os
from ryuu_messaging_core import ChannelOrchestrator
from ryuu_messaging_telegram import TelegramAdapter

tg = TelegramAdapter(
    bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
    on_clear=my_clear_callback,        # all callbacks optional
    on_verbose=my_verbose_callback,
    on_model=my_model_callback,
    on_settings=my_settings_callback,
    on_status=my_status_callback,
    on_current_model=my_current_model_callback,
    allowed_models=("gpt-4o-mini", "gpt-4o"),
)
orch.register_channel(tg)
```

Webhook mode + Slack/Discord-style group memory are roadmap items (Phase 9.4+).
