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

from bot import handlers


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (create the bot with BotFather).")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("buy", handlers.buy))
    app.add_handler(CommandHandler("sell", handlers.sell))
    app.add_handler(CallbackQueryHandler(handlers.on_button))
    app.run_polling()


if __name__ == "__main__":
    main()