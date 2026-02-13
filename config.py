"""Configuration module for Telegram Bot.

Loads bot token from environment variables.
The token should be stored in a .env file in the project root:
    BOT_TOKEN=your_telegram_bot_token_here

Never commit your actual token to version control!
"""

import os

from dotenv import load_dotenv  # For loading .env file

# Load environment variables from .env file
load_dotenv()

# Get bot token from environment variable
# This token is obtained from @BotFather on Telegram
API_TOKEN = os.getenv("BOT_TOKEN")