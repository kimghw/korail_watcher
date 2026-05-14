import logging
from unittest.mock import AsyncMock

from srt_watcher.notifier.telegram import TelegramNotifier


def test_telegram_notifier_sends():
    bot = AsyncMock()
    notifier = TelegramNotifier("token", "chat", bot=bot)
    notifier.notify("hello")
    bot.send_message.assert_awaited_once_with(chat_id="chat", text="hello")


def test_telegram_notifier_warns_on_failure(caplog):
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("boom")
    notifier = TelegramNotifier("token", "chat", bot=bot)
    with caplog.at_level(logging.WARNING):
        notifier.notify("test")
    assert "Telegram notification failed" in caplog.text
