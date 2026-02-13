# telegrambot-friengineers

An advanced Telegram bot that combines an RSS/Feed reader, task and reminder manager, file organizer/converter, and QR generator.

## Features

- RSS/Feed subscriptions and latest updates
- Task list with completion tracking
- Scheduled reminders (UTC)
- File manager with image conversion (PNG/JPG)
- QR code generation from text or URL

## Requirements

- Python 3.10+
- Telegram bot token from BotFather

## Setup (Windows PowerShell)

1. Create and activate a virtual environment (recommended):

```powershell
python -m venv .venv
\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create a `.env` file in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
```

## Run

```powershell
python main.py
```

## Commands

- `/start` - welcome + help
- `/help` - show help

RSS / Feeds:
- `/rss_add <url>`
- `/rss_list`
- `/rss_remove <id|url>`
- `/rss_latest`

Tasks / Reminders:
- `/task_add <text>`
- `/task_list`
- `/task_done <id>`
- `/remind_add <YYYY-MM-DD HH:MM> <text>` (UTC)
- `/remind_list`
- `/remind_cancel <id>`

Files / Converter:
- Send a file or photo to save it
- `/files_list`
- `/files_get <name>`
- `/convert_png`
- `/convert_jpg`

Utilities:
- `/qr <text or url>`

## Notes

- Reminders use UTC time.
- Send a file or photo before using the convert commands.
- Keep your bot token in `.env` and never commit it to GitHub.