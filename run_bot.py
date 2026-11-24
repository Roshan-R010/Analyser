"""Start the Telegram bot:  .venv/Scripts/python run_bot.py   (settings in .env, see .env.example)"""
import sys

from analyser.frontends.tgbot import main

if __name__ == "__main__":
    sys.exit(main())
