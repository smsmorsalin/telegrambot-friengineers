"""Advanced Telegram Bot with multiple features.

Features:
- RSS/Feed Reader: Subscribe and read RSS feeds
- Task Manager: Create and track tasks
- Reminder System: Schedule reminders with UTC time
- File Manager: Save, list, and retrieve files
- Image Converter: Convert images between formats (PNG, JPG)
- QR Generator: Create QR codes from text or URLs

Author: SMS
Repository: https://github.com/YOUR_USERNAME/telegrambot-friengineers
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from pathlib import Path

import feedparser  # For parsing RSS/Atom feeds
import qrcode  # For generating QR codes
from PIL import Image  # For image conversion
from telegram import InputFile, Update  # Telegram bot types
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)  # Bot handlers

from config import API_TOKEN  # Bot token from .env file


# ===========================
# CONFIGURATION & CONSTANTS
# ===========================

# Directory structure for bot data storage
BASE_DIR = Path(__file__).parent  # Project root directory
DATA_DIR = BASE_DIR / "data"  # Main data directory
FILES_DIR = DATA_DIR / "files"  # User files storage
DB_PATH = DATA_DIR / "bot.db"  # SQLite database path

# DateTime format for reminders (YYYY-MM-DD HH:MM)
DATETIME_FMT = "%Y-%m-%d %H:%M"


# ===========================
# DATABASE & STORAGE SETUP
# ===========================

def init_dirs() -> None:
    """Create necessary directories for bot data storage.
    
    Creates:
    - data/: Main data directory
    - data/files/: User files storage
    """
    DATA_DIR.mkdir(exist_ok=True)
    FILES_DIR.mkdir(exist_ok=True)


def get_db() -> sqlite3.Connection:
    """Get SQLite database connection with Row factory.
    
    Returns:
        sqlite3.Connection: Database connection with row_factory set
                           to access columns by name.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Allow dict-like access to rows
    return conn


def init_db() -> None:
    """Initialize database tables if they don't exist.
    
    Creates four tables:
    - users: Store user information (id, username, names)
    - feeds: User's RSS feed subscriptions
    - tasks: Todo tasks with completion status
    - reminders: Scheduled reminders with UTC timestamps
    """
    with get_db() as conn:
        conn.executescript(
            """
            -- User information table
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,           -- Telegram user ID
                username TEXT,                     -- Telegram username
                first_name TEXT,                   -- User's first name
                last_name TEXT,                    -- User's last name
                created_at TEXT                    -- Account creation timestamp
            );

            -- RSS feed subscriptions
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Feed ID
                user_id INTEGER NOT NULL,              -- Owner's Telegram ID
                url TEXT NOT NULL,                     -- RSS feed URL
                title TEXT,                            -- Feed title
                created_at TEXT                        -- Subscription timestamp
            );

            -- Task/Todo list
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Task ID
                user_id INTEGER NOT NULL,              -- Owner's Telegram ID
                text TEXT NOT NULL,                    -- Task description
                is_done INTEGER NOT NULL DEFAULT 0,    -- Completion status (0=pending, 1=done)
                created_at TEXT                        -- Creation timestamp
            );

            -- Scheduled reminders
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Reminder ID
                user_id INTEGER NOT NULL,              -- Owner's Telegram ID
                remind_at TEXT NOT NULL,               -- When to remind (ISO format, UTC)
                text TEXT NOT NULL,                    -- Reminder message
                created_at TEXT                        -- Creation timestamp
            );
            """
        )


# ===========================
# UTILITY FUNCTIONS
# ===========================

def now_utc() ->  dt.datetime:
    """Get current UTC datetime.
    
    Returns:
        dt.datetime: Current date and time in UTC timezone.
    """
    return dt.datetime.now(dt.timezone.utc)


def upsert_user(update: Update) -> None:
    """Save or update user information in database.
    
    Uses INSERT OR IGNORE to avoid duplicate entries.
    Called at the start of every command to track users.
    
    Args:
        update: Telegram Update object containing user info.
    """
    if not update.effective_user:
        return
    user = update.effective_user
    created_at = now_utc().isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, username, first_name, last_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user.id, user.username, user.first_name, user.last_name, created_at),
        )


def ensure_user_dir(user_id: int) -> Path:
    """Create and return user-specific file storage directory.
    
    Each user gets their own subdirectory in data/files/
    to keep their uploaded files separate.
    
    Args:
        user_id: Telegram user ID.
    
    Returns:
        Path: Path to user's file directory.
    """
    user_dir = FILES_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)  # Create if doesn't exist
    return user_dir


# ===========================
# HELP & WELCOME MESSAGES
# ===========================

def format_help() -> str:
    """Generate formatted help message with all available commands.
    
    Returns:
        str: HTML-formatted help text with emojis and command descriptions.
    """
    return (
        "📚 <b>Available Commands</b>\n\n"
        "🏠 <b>General</b>\n"
        "/start - Welcome message\n"
        "/help - Show this help\n\n"
        "📰 <b>RSS / Feeds</b>\n"
        "/rss_add &lt;url&gt; - Subscribe to RSS feed\n"
        "/rss_list - Show your feeds\n"
        "/rss_remove &lt;id|url&gt; - Unsubscribe\n"
        "/rss_latest - Get latest entries\n\n"
        "✅ <b>Tasks & Reminders</b>\n"
        "/task_add &lt;text&gt; - Create new task\n"
        "/task_list - Show all tasks\n"
        "/task_done &lt;id&gt; - Mark task complete\n"
        "/remind_add &lt;YYYY-MM-DD HH:MM&gt; &lt;text&gt; - Set reminder (UTC)\n"
        "/remind_list - Show reminders\n"
        "/remind_cancel &lt;id&gt; - Cancel reminder\n\n"
        "📁 <b>Files & Converter</b>\n"
        "📤 Send any file or photo to save it\n"
        "/files_list - View saved files\n"
        "/files_get &lt;name&gt; - Download file\n"
        "/convert_png - Convert last image to PNG\n"
        "/convert_jpg - Convert last image to JPG\n\n"
        "🔧 <b>Utilities</b>\n"
        "/qr &lt;text or url&gt; - Generate QR code\n"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - send welcome message with help.
    
    Args:
        update: Telegram Update object.
        context: Bot context with user data.
    """
    upsert_user(update)  # Save user info to database
    user = update.effective_user
    name = user.first_name if user else "there"
    await update.message.reply_text(
        f"👋 <b>Welcome {name}!</b>\n\n"
        f"I'm your multi-purpose assistant bot. "
        f"I can help you with RSS feeds, tasks, reminders, file management, and more!\n\n"
        f"{format_help()}",
        parse_mode="HTML"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command - show available commands.
    
    Args:
        update: Telegram Update object.
        context: Bot context.
    """
    await update.message.reply_text(format_help(), parse_mode="HTML")


def parse_args_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Extract and join command arguments into a single string.
    
    Args:
        context: Bot context containing command arguments.
    
    Returns:
        str: Joined arguments with whitespace stripped.
    """
    return " ".join(context.args).strip()


# ===========================
# RSS FEED COMMANDS
# ===========================


async def rss_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subscribe to an RSS/Atom feed.
    
    Usage: /rss_add <url>
    Example: /rss_add https://example.com/feed.xml
    
    Args:
        update: Telegram Update object.
        context: Bot context with command arguments.
    """
    upsert_user(update)
    url = parse_args_text(context)
    
    # Validate URL provided
    if not url:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/rss_add &lt;url&gt;</code>\n\n"
            "<b>Example:</b> <code>/rss_add https://example.com/feed.xml</code>",
            parse_mode="HTML"
        )
        return

    # Try to parse the feed
    feed = feedparser.parse(url)
    # Check if feed is valid (bozo=True means parsing error, no entries=empty feed)
    if feed.bozo and not feed.entries:
        await update.message.reply_text(
            "⚠️ <b>Feed not valid or unreachable.</b>\n\n"
            "Please check the URL and try again.",
            parse_mode="HTML"
        )
        return

    # Extract feed title if available
    title = feed.feed.get("title") if feed.feed else None
    created_at = now_utc().isoformat()
    
    # Save feed to database
    with get_db() as conn:
        conn.execute(
            "INSERT INTO feeds (user_id, url, title, created_at) VALUES (?, ?, ?, ?)",
            (update.effective_user.id, url, title, created_at),
        )
    
    feed_name = title or "Feed"
    await update.message.reply_text(
        f"✅ <b>Feed added successfully!</b>\n\n📰 {feed_name}",
        parse_mode="HTML"
    )


async def rss_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all subscribed RSS feeds for the user.
    
    Usage: /rss_list
    
    Args:
        update: Telegram Update object.
        context: Bot context.
    """
    upsert_user(update)
    # Get all feeds for this user
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, url, title FROM feeds WHERE user_id = ? ORDER BY id",
            (update.effective_user.id,),
        ).fetchall()
    
    # Check if user has any feeds
    if not rows:
        await update.message.reply_text(
            "📭 <b>No feeds yet.</b>\n\n"
            "Add one with <code>/rss_add &lt;url&gt;</code>",
            parse_mode="HTML"
        )
        return
    
    # Build feed list message
    lines = ["📰 <b>Your RSS Feeds:</b>\n"]
    for row in rows:
        label = row["title"] or row["url"]  # Use title if available, otherwise URL
        lines.append(f"<code>{row['id']}</code>. {label}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def rss_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unsubscribe from an RSS feed by ID or URL.
    
    Usage: /rss_remove <id|url>
    Example: /rss_remove 1
    
    Args:
        update: Telegram Update object.
        context: Bot context with command arguments.
    """
    upsert_user(update)
    target = parse_args_text(context)
    if not target:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/rss_remove &lt;id|url&gt;</code>\n\n"
            "<b>Example:</b> <code>/rss_remove 1</code>",
            parse_mode="HTML"
        )
        return

    # Delete feed by ID (number) or URL (string)
    with get_db() as conn:
        if target.isdigit():  # If target is a number, treat as feed ID
            result = conn.execute(
                "DELETE FROM feeds WHERE user_id = ? AND id = ?",
                (update.effective_user.id, int(target)),
            )
        else:  # Otherwise treat as URL
            result = conn.execute(
                "DELETE FROM feeds WHERE user_id = ? AND url = ?",
                (update.effective_user.id, target),
            )
    
    # Check if deletion was successful
    if result.rowcount:
        await update.message.reply_text("🗑️ <b>Feed removed successfully!</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Feed not found.</b>", parse_mode="HTML")


async def rss_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch and display latest entries from all subscribed feeds.
    
    Shows up to 3 latest entries per feed.
    Usage: /rss_latest
    
    Args:
        update: Telegram Update object.
        context: Bot context.
    """
    upsert_user(update)
    
    # Get all user's feeds
    with get_db() as conn:
        rows = conn.execute(
            "SELECT url, title FROM feeds WHERE user_id = ? ORDER BY id",
            (update.effective_user.id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text(
            "📭 <b>No feeds yet.</b>\n\n"
            "Add one with <code>/rss_add &lt;url&gt;</code>",
            parse_mode="HTML"
        )
        return

    # Show loading message
    await update.message.reply_text("⏳ <b>Fetching latest entries...</b>", parse_mode="HTML")
    
    # Build message with entries from each feed
    chunks: list[str] = ["📰 <b>Latest Feed Entries:</b>\n"]
    for row in rows:
        feed = feedparser.parse(row["url"])  # Parse RSS feed
        title = row["title"] or feed.feed.get("title") or row["url"]
        entries = feed.entries[:3]  # Get only first 3 entries
        chunks.append(f"\n<b>{title}</b>")
        if not entries:
            chunks.append("• <i>(no entries)</i>")
            continue
        # Add each entry with title and link
        for entry in entries:
            entry_title = entry.get("title") or "(no title)"
            entry_link = entry.get("link") or ""
            chunks.append(f"• {entry_title}")
            if entry_link:
                chunks.append(f"  {entry_link}")

    await update.message.reply_text("\n".join(chunks), parse_mode="HTML")


# ===========================
# TASK MANAGEMENT COMMANDS
# ===========================

async def task_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a new task to the user's todo list.
    
    Usage: /task_add <text>
    Example: /task_add Buy groceries
    
    Args:
        update: Telegram Update object.
        context: Bot context with task text.
    """
    upsert_user(update)
    text = parse_args_text(context)
    
    # Validate task text provided
    if not text:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/task_add &lt;text&gt;</code>\n\n"
            "<b>Example:</b> <code>/task_add Buy groceries</code>",
            parse_mode="HTML"
        )
        return
    
    # Save task to database
    created_at = now_utc().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO tasks (user_id, text, created_at) VALUES (?, ?, ?)",
            (update.effective_user.id, text, created_at),
        )
    await update.message.reply_text(
        f"✅ <b>Task added!</b>\n\n📝 {text}",
        parse_mode="HTML"
    )


async def task_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display all tasks for the user with completion status.
    
    Usage: /task_list
    Shows: ✅ for completed tasks, ⬜ for pending tasks
    
    Args:
        update: Telegram Update object.
        context: Bot context.
    """
    upsert_user(update)
    
    # Get all user's tasks
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, text, is_done FROM tasks WHERE user_id = ? ORDER BY id",
            (update.effective_user.id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text(
            "📋 <b>No tasks yet.</b>\n\n"
            "Add one with <code>/task_add &lt;text&gt;</code>",
            parse_mode="HTML"
        )
        return
    
    # Build task list with status indicators
    lines = ["📋 <b>Your Tasks:</b>\n"]
    for row in rows:
        status = "✅" if row["is_done"] else "⬜"  # Checkbox visual
        lines.append(f"{status} <code>{row['id']}</code>. {row['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def task_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark a task as completed.
    
    Usage: /task_done <id>
    Example: /task_done 1
    
    Args:
        update: Telegram Update object.
        context: Bot context with task ID.
    """
    upsert_user(update)
    target = parse_args_text(context)
    
    # Validate task ID provided
    if not target or not target.isdigit():
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/task_done &lt;id&gt;</code>\n\n"
            "<b>Example:</b> <code>/task_done 1</code>",
            parse_mode="HTML"
        )
        return
    
    # Update task status to done (is_done = 1)
    with get_db() as conn:
        result = conn.execute(
            "UPDATE tasks SET is_done = 1 WHERE user_id = ? AND id = ?",
            (update.effective_user.id, int(target)),
        )
    if result.rowcount:
        await update.message.reply_text("✅ <b>Task completed!</b> Great job!", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Task not found.</b>", parse_mode="HTML")


# ===========================
# REMINDER SYSTEM COMMANDS
# ===========================

def parse_remind_time(raw: str) -> dt.datetime | None:
    """Parse datetime string into UTC datetime object.
    
    Args:
        raw: Datetime string in format "YYYY-MM-DD HH:MM"
    
    Returns:
        dt.datetime | None: Parsed datetime in UTC, or None if invalid format.
    """
    try:
        parsed = dt.datetime.strptime(raw, DATETIME_FMT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt.timezone.utc)


def schedule_reminder(
    app: Application,
    reminder_id: int,
    user_id: int,
    text: str,
    remind_at: dt.datetime,
) -> None:
    """Schedule a reminder job to run at specified time.
    
    Args:
        app: Telegram Application instance.
        reminder_id: Database ID of the reminder.
        user_id: Telegram user ID to send reminder to.
        text: Reminder message text.
        remind_at: When to send the reminder (UTC).
    """
    # Calculate delay in seconds from now until reminder time
    delay = max(0, (remind_at - now_utc()).total_seconds())
    
    # Schedule job in Telegram's job queue
    app.job_queue.run_once(
        reminder_job,  # Function to call
        delay,  # Seconds to wait
        name=f"reminder_{reminder_id}",  # Job name for later reference
        data={"reminder_id": reminder_id, "user_id": user_id, "text": text},
    )


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job function executed when reminder time arrives.
    
    Sends reminder message to user and deletes reminder from database.
    
    Args:
        context: Job context containing reminder data.
    """
    data = context.job.data
    user_id = data["user_id"]
    text = data["text"]
    reminder_id = data["reminder_id"]
    
    # Send reminder message to user
    await context.bot.send_message(
        chat_id=user_id,
        text=f"⏰ <b>REMINDER!</b>\n\n{text}",
        parse_mode="HTML"
    )
    
    # Delete reminder from database after sending
    with get_db() as conn:
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))


async def remind_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a new scheduled reminder.
    
    Usage: /remind_add <YYYY-MM-DD HH:MM> <text>
    Example: /remind_add 2026-02-15 14:30 Meeting with team
    Time must be in UTC.
    
    Args:
        update: Telegram Update object.
        context: Bot context with datetime and reminder text.
    """
    upsert_user(update)
    # Need at least date, time, and message text
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/remind_add &lt;YYYY-MM-DD HH:MM&gt; &lt;text&gt;</code> (UTC)\n\n"
            "<b>Example:</b> <code>/remind_add 2026-02-15 14:30 Meeting with team</code>",
            parse_mode="HTML"
        )
        return
    
    # Extract date/time (first 2 args) and message (remaining args)
    when_raw = " ".join(context.args[:2])  # "YYYY-MM-DD HH:MM"
    text = " ".join(context.args[2:]).strip()  # Reminder message
    
    # Validate message text provided
    if not text:
        await update.message.reply_text(
            "❌ <b>Please provide reminder text.</b>",
            parse_mode="HTML"
        )
        return
    
    # Parse and validate datetime
    remind_at = parse_remind_time(when_raw)
    if not remind_at:  # Invalid format
        await update.message.reply_text(
            "❌ <b>Invalid datetime format.</b>\n\n"
            "Use <code>YYYY-MM-DD HH:MM</code> (UTC)\n\n"
            "<b>Example:</b> <code>2026-02-15 14:30</code>",
            parse_mode="HTML"
        )
        return
    
    # Save reminder to database
    created_at = now_utc().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (user_id, remind_at, text, created_at) VALUES (?, ?, ?, ?)",
            (update.effective_user.id, remind_at.isoformat(), text, created_at),
        )
        reminder_id = cur.lastrowid  # Get auto-generated ID
    
    # Schedule the reminder job
    schedule_reminder(context.application, reminder_id, update.effective_user.id, text, remind_at)
    await update.message.reply_text(
        f"⏰ <b>Reminder set!</b>\n\n"
        f"📅 <code>{when_raw}</code> UTC\n"
        f"📝 {text}",
        parse_mode="HTML"
    )


async def remind_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all scheduled reminders for the user.
    
    Usage: /remind_list
    Shows reminder ID, time (UTC), and message text.
    
    Args:
        update: Telegram Update object.
        context: Bot context.
    """
    upsert_user(update)
    
    # Get all user's reminders sorted by time
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, remind_at, text FROM reminders WHERE user_id = ? ORDER BY remind_at",
            (update.effective_user.id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text(
            "⏰ <b>No reminders scheduled.</b>\n\n"
            "Create one with <code>/remind_add &lt;date time&gt; &lt;text&gt;</code>",
            parse_mode="HTML"
        )
        return
    lines = ["⏰ <b>Your Reminders</b> (UTC):\n"]
    for row in rows:
        lines.append(f"<code>{row['id']}</code>. 📅 <code>{row['remind_at']}</code> - {row['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def remind_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel a scheduled reminder.
    
    Usage: /remind_cancel <id>
    Example: /remind_cancel 1
    
    Args:
        update: Telegram Update object.
        context: Bot context with reminder ID.
    """
    upsert_user(update)
    target = parse_args_text(context)
    if not target or not target.isdigit():
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/remind_cancel &lt;id&gt;</code>\n\n"
            "<b>Example:</b> <code>/remind_cancel 1</code>",
            parse_mode="HTML"
        )
        return
    reminder_id = int(target)
    
    # Delete reminder from database
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM reminders WHERE user_id = ? AND id = ?",
            (update.effective_user.id, reminder_id),
        )
    
    # Cancel the scheduled job if it exists
    jobs = context.application.job_queue.get_jobs_by_name(f"reminder_{reminder_id}")
    for job in jobs:
        job.schedule_removal()  # Remove from job queue
    if result.rowcount:
        await update.message.reply_text("✅ <b>Reminder canceled!</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Reminder not found.</b>", parse_mode="HTML")


# ===========================
# FILE MANAGEMENT COMMANDS
# ===========================

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming files and photos - save to user's directory.
    
    Triggered when user sends a file or photo.
    Saves file to data/files/<user_id>/ directory.
    
    Args:
        update: Telegram Update object with file/photo.
        context: Bot context for storing file path.
    """
    upsert_user(update)
    user_id = update.effective_user.id
    user_dir = ensure_user_dir(user_id)  # Get/create user's directory
    saved_path: Path | None = None

    # Handle document (any file)
    if update.message.document:
        doc = update.message.document
        file = await doc.get_file()
        safe_name = doc.file_name or f"file_{doc.file_unique_id}"  # Use original name or generate one
        saved_path = user_dir / safe_name
        await file.download_to_drive(saved_path)  # Download file from Telegram servers

    # Handle photo
    elif update.message.photo:
        photo = update.message.photo[-1]  # Get highest resolution version
        file = await photo.get_file()
        saved_path = user_dir / f"photo_{photo.file_unique_id}.jpg"
        await file.download_to_drive(saved_path)

    if saved_path:
        # Store file path in user context for convert commands
        context.user_data["last_file"] = str(saved_path)
        await update.message.reply_text(
            f"✅ <b>File saved!</b>\n\n"
            f"📁 <code>{saved_path.name}</code>\n\n"
            f"Use <code>/files_list</code> to view all files or <code>/convert_png</code> <code>/convert_jpg</code> to convert images.",
            parse_mode="HTML"
        )


async def files_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all files saved by the user.
    
    Usage: /files_list
    Shows numbered list of all files in user's directory.
    
    Args:
        update: Telegram Update object.
        context: Bot context.
    """
    upsert_user(update)
    user_dir = ensure_user_dir(update.effective_user.id)
    # Get all files in user's directory (excluding subdirectories)
    files = [p.name for p in user_dir.iterdir() if p.is_file()]
    if not files:
        await update.message.reply_text(
            "📁 <b>No files saved yet.</b>\n\n"
            "Send a file or photo to get started!",
            parse_mode="HTML"
        )
        return
    lines = ["📁 <b>Your Files:</b>\n"]
    for idx, f in enumerate(files, 1):
        lines.append(f"<code>{idx}</code>. {f}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def files_get(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieve and send a previously saved file.
    
    Usage: /files_get <name>
    Example: /files_get photo_123.jpg
    
    Args:
        update: Telegram Update object.
        context: Bot context with filename.
    """
    upsert_user(update)
    name = parse_args_text(context)
    if not name:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/files_get &lt;name&gt;</code>\n\n"
            "<b>Example:</b> <code>/files_get photo_123.jpg</code>",
            parse_mode="HTML"
        )
        return
    user_dir = ensure_user_dir(update.effective_user.id)
    target = user_dir / name  # Build full file path
    
    # Check if file exists
    if not target.exists():
        await update.message.reply_text(
            "❌ <b>File not found.</b>\n\n"
            "Use <code>/files_list</code> to see available files.",
            parse_mode="HTML"
        )
        return
    
    # Send file to user
    await update.message.reply_text("📤 <b>Sending file...</b>", parse_mode="HTML")
    await update.message.reply_document(document=InputFile(target))


# ===========================
# IMAGE CONVERSION COMMANDS
# ===========================

def is_image(path: Path) -> bool:
    """Check if file is a supported image format.
    
    Args:
        path: File path to check.
    
    Returns:
        bool: True if file extension is a supported image format.
    """
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


async def convert_image(update: Update, context: ContextTypes.DEFAULT_TYPE, fmt: str) -> None:
    """Convert last uploaded image to specified format.
    
    Args:
        update: Telegram Update object.
        context: Bot context with last_file reference.
        fmt: Target format ('png' or 'jpg').
    """
    upsert_user(update)
    # Get last uploaded file path from context
    last_file = context.user_data.get("last_file")
    if not last_file:  # No file uploaded yet
        await update.message.reply_text(
            "❌ <b>No image found.</b>\n\n"
            "Send an image first, then run <code>/convert_png</code> or <code>/convert_jpg</code>.",
            parse_mode="HTML"
        )
        return
    
    src = Path(last_file)
    # Validate file exists and is an image
    if not src.exists() or not is_image(src):
        await update.message.reply_text(
            "❌ <b>Last file is not an image.</b>\n\n"
            "Please send a valid image file.",
            parse_mode="HTML"
        )
        return
    
    # Show conversion progress
    await update.message.reply_text(f"🔄 <b>Converting to {fmt.upper()}...</b>", parse_mode="HTML")
    
    # Convert image using PIL
    out_path = src.with_suffix(f".{fmt}")  # Change file extension
    with Image.open(src) as img:
        img.save(out_path, format=fmt.upper())  # Save in new format
    
    # Update last_file to converted file
    context.user_data["last_file"] = str(out_path)
    await update.message.reply_text(
        f"✅ <b>Conversion complete!</b>\n\n📄 <code>{out_path.name}</code>",
        parse_mode="HTML"
    )
    await update.message.reply_document(document=InputFile(out_path))


async def convert_png(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Convert last image to PNG format.
    
    Usage: /convert_png
    Requires: User must have sent an image first.
    """
    await convert_image(update, context, "png")


async def convert_jpg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Convert last image to JPG format.
    
    Usage: /convert_jpg
    Requires: User must have sent an image first.
    """
    await convert_image(update, context, "jpg")


# ===========================
# QR CODE GENERATOR
# ===========================

async def qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate QR code from text or URL.
    
    Usage: /qr <text or url>
    Example: /qr https://github.com
    
    Args:
        update: Telegram Update object.
        context: Bot context with text to encode.
    """
    upsert_user(update)
    text = parse_args_text(context)
    if not text:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/qr &lt;text or url&gt;</code>\n\n"
            "<b>Example:</b> <code>/qr https://github.com</code>",
            parse_mode="HTML"
        )
        return
    
    # Show generation progress
    await update.message.reply_text("🔄 <b>Generating QR code...</b>", parse_mode="HTML")
    
    # Generate QR code
    img = qrcode.make(text)  # Create QR code image
    out_path = DATA_DIR / f"qr_{update.effective_user.id}.png"  # Unique filename per user
    img.save(out_path)  # Save as PNG
    
    # Send QR code to user
    await update.message.reply_text("✅ <b>QR code generated!</b>", parse_mode="HTML")
    await update.message.reply_document(document=InputFile(out_path))


# ===========================
# BOT INITIALIZATION
# ===========================

def schedule_pending_reminders(app: Application) -> None:
    """Re-schedule reminders after bot restart.
    
    Loads all pending reminders from database and schedules them.
    Called during bot initialization to restore scheduled jobs.
    
    Args:
        app: Telegram Application instance.
    """    
    # Get all reminders from database
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, user_id, remind_at, text FROM reminders"
        ).fetchall()
    
    # Schedule each reminder that hasn't passed yet
    for row in rows:
        remind_at = dt.datetime.fromisoformat(row["remind_at"])
        if remind_at < now_utc():  # Skip past reminders
            continue
        schedule_reminder(app, row["id"], row["user_id"], row["text"], remind_at)


def main() -> None:
    """Main function - initialize and run the bot.
    
    Steps:
    1. Configure logging
    2. Validate bot token
    3. Initialize directories and database
    4. Register command handlers
    5. Restore pending reminders
    6. Start polling for updates
    """
    # Configure logging to console
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    
    # Validate bot token is configured
    if not API_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in .env or environment variables.")

    # Initialize storage
    init_dirs()  # Create data directories
    init_db()  # Create database tables

    # Build Telegram bot application
    app = Application.builder().token(API_TOKEN).build()

    # Register command handlers
    # General commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # RSS feed commands
    app.add_handler(CommandHandler("rss_add", rss_add))
    app.add_handler(CommandHandler("rss_list", rss_list))
    app.add_handler(CommandHandler("rss_remove", rss_remove))
    app.add_handler(CommandHandler("rss_latest", rss_latest))

    # Task management commands
    app.add_handler(CommandHandler("task_add", task_add))
    app.add_handler(CommandHandler("task_list", task_list))
    app.add_handler(CommandHandler("task_done", task_done))

    # Reminder commands
    app.add_handler(CommandHandler("remind_add", remind_add))
    app.add_handler(CommandHandler("remind_list", remind_list))
    app.add_handler(CommandHandler("remind_cancel", remind_cancel))

    # File management commands
    app.add_handler(CommandHandler("files_list", files_list))
    app.add_handler(CommandHandler("files_get", files_get))
    app.add_handler(CommandHandler("convert_png", convert_png))
    app.add_handler(CommandHandler("convert_jpg", convert_jpg))

    # QR code generator
    app.add_handler(CommandHandler("qr", qr_code))

    # Handle incoming files and photos (non-command messages)
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))

    # Restore reminders from database after restart
    schedule_pending_reminders(app)
    
    # Start bot - polls Telegram servers for updates
    app.run_polling()


# Entry point - run bot when script is executed directly
if __name__ == "__main__":
    main()
