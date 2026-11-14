"""Bot entrypoint. From the repo root:

    pip install -r requirements.txt
    copy .env.example .env   # put the BotFather token in
    python -m bot.app

Defaults to USE_FAKE_DATA=1, so it works before Julius's and Kiril's code lands.
"""
from dotenv import load_dotenv

load_dotenv()  # must run before orchestrator is imported (it reads env at import time)

import os

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

import obs
from bot import handlers


async def _on_error(update, context) -> None:
    """One readable line instead of a traceback wall; a second bot on the same token is the usual cause."""
    from telegram.error import Conflict, NetworkError

    err = context.error
    if isinstance(err, Conflict):
        print("⚠️  Another copy of this bot is running with the same token. Stop the other one.", flush=True)
    elif isinstance(err, NetworkError):
        print(f"⚠️  Telegram network hiccup: {err}", flush=True)
    else:
        import traceback
        traceback.print_exception(err)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (create the bot with BotFather).")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("buy", handlers.buy))
    app.add_handler(CommandHandler("sell", handlers.sell))
    app.add_handler(CommandHandler("stats", handlers.stats))
    app.add_handler(CallbackQueryHandler(handlers.on_button))
    app.add_error_handler(_on_error)
    obs.emit("bot_started", pid=os.getpid())
    app.run_polling()


if __name__ == "__main__":
    main()