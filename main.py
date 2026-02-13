from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from pathlib import Path

import feedparser
import qrcode
from PIL import Image
from telegram import InputFile, Update
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from config import API_TOKEN


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
FILES_DIR = DATA_DIR / "files"
DB_PATH = DATA_DIR / "bot.db"

DATETIME_FMT = "%Y-%m-%d %H:%M"


def init_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    FILES_DIR.mkdir(exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                is_done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                remind_at TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT
            );
            """
        )


def now_utc() ->  dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def upsert_user(update: Update) -> None:
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
    user_dir = FILES_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def format_help() -> str:
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
    upsert_user(update)
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
    await update.message.reply_text(format_help(), parse_mode="HTML")


def parse_args_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args).strip()


async def rss_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    url = parse_args_text(context)
    if not url:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/rss_add &lt;url&gt;</code>\n\n"
            "<b>Example:</b> <code>/rss_add https://example.com/feed.xml</code>",
            parse_mode="HTML"
        )
        return

    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        await update.message.reply_text(
            "⚠️ <b>Feed not valid or unreachable.</b>\n\n"
            "Please check the URL and try again.",
            parse_mode="HTML"
        )
        return

    title = feed.feed.get("title") if feed.feed else None
    created_at = now_utc().isoformat()
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
    upsert_user(update)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, url, title FROM feeds WHERE user_id = ? ORDER BY id",
            (update.effective_user.id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text(
            "📭 <b>No feeds yet.</b>\n\n"
            "Add one with <code>/rss_add &lt;url&gt;</code>",
            parse_mode="HTML"
        )
        return
    lines = ["📰 <b>Your RSS Feeds:</b>\n"]
    for row in rows:
        label = row["title"] or row["url"]
        lines.append(f"<code>{row['id']}</code>. {label}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def rss_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    target = parse_args_text(context)
    if not target:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/rss_remove &lt;id|url&gt;</code>\n\n"
            "<b>Example:</b> <code>/rss_remove 1</code>",
            parse_mode="HTML"
        )
        return

    with get_db() as conn:
        if target.isdigit():
            result = conn.execute(
                "DELETE FROM feeds WHERE user_id = ? AND id = ?",
                (update.effective_user.id, int(target)),
            )
        else:
            result = conn.execute(
                "DELETE FROM feeds WHERE user_id = ? AND url = ?",
                (update.effective_user.id, target),
            )
    if result.rowcount:
        await update.message.reply_text("🗑️ <b>Feed removed successfully!</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Feed not found.</b>", parse_mode="HTML")


async def rss_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
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

    await update.message.reply_text("⏳ <b>Fetching latest entries...</b>", parse_mode="HTML")
    chunks: list[str] = ["📰 <b>Latest Feed Entries:</b>\n"]
    for row in rows:
        feed = feedparser.parse(row["url"])
        title = row["title"] or feed.feed.get("title") or row["url"]
        entries = feed.entries[:3]
        chunks.append(f"\n<b>{title}</b>")
        if not entries:
            chunks.append("• <i>(no entries)</i>")
            continue
        for entry in entries:
            entry_title = entry.get("title") or "(no title)"
            entry_link = entry.get("link") or ""
            chunks.append(f"• {entry_title}")
            if entry_link:
                chunks.append(f"  {entry_link}")

    await update.message.reply_text("\n".join(chunks), parse_mode="HTML")


async def task_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    text = parse_args_text(context)
    if not text:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/task_add &lt;text&gt;</code>\n\n"
            "<b>Example:</b> <code>/task_add Buy groceries</code>",
            parse_mode="HTML"
        )
        return
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
    upsert_user(update)
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
    lines = ["📋 <b>Your Tasks:</b>\n"]
    for row in rows:
        status = "✅" if row["is_done"] else "⬜"
        lines.append(f"{status} <code>{row['id']}</code>. {row['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def task_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    target = parse_args_text(context)
    if not target or not target.isdigit():
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/task_done &lt;id&gt;</code>\n\n"
            "<b>Example:</b> <code>/task_done 1</code>",
            parse_mode="HTML"
        )
        return
    with get_db() as conn:
        result = conn.execute(
            "UPDATE tasks SET is_done = 1 WHERE user_id = ? AND id = ?",
            (update.effective_user.id, int(target)),
        )
    if result.rowcount:
        await update.message.reply_text("✅ <b>Task completed!</b> Great job!", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Task not found.</b>", parse_mode="HTML")


def parse_remind_time(raw: str) -> dt.datetime | None:
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
    delay = max(0, (remind_at - now_utc()).total_seconds())
    app.job_queue.run_once(
        reminder_job,
        delay,
        name=f"reminder_{reminder_id}",
        data={"reminder_id": reminder_id, "user_id": user_id, "text": text},
    )


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    user_id = data["user_id"]
    text = data["text"]
    reminder_id = data["reminder_id"]
    await context.bot.send_message(
        chat_id=user_id,
        text=f"⏰ <b>REMINDER!</b>\n\n{text}",
        parse_mode="HTML"
    )
    with get_db() as conn:
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))


async def remind_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/remind_add &lt;YYYY-MM-DD HH:MM&gt; &lt;text&gt;</code> (UTC)\n\n"
            "<b>Example:</b> <code>/remind_add 2026-02-15 14:30 Meeting with team</code>",
            parse_mode="HTML"
        )
        return
    when_raw = " ".join(context.args[:2])
    text = " ".join(context.args[2:]).strip()
    if not text:
        await update.message.reply_text(
            "❌ <b>Please provide reminder text.</b>",
            parse_mode="HTML"
        )
        return
    remind_at = parse_remind_time(when_raw)
    if not remind_at:
        await update.message.reply_text(
            "❌ <b>Invalid datetime format.</b>\n\n"
            "Use <code>YYYY-MM-DD HH:MM</code> (UTC)\n\n"
            "<b>Example:</b> <code>2026-02-15 14:30</code>",
            parse_mode="HTML"
        )
        return
    created_at = now_utc().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (user_id, remind_at, text, created_at) VALUES (?, ?, ?, ?)",
            (update.effective_user.id, remind_at.isoformat(), text, created_at),
        )
        reminder_id = cur.lastrowid
    schedule_reminder(context.application, reminder_id, update.effective_user.id, text, remind_at)
    await update.message.reply_text(
        f"⏰ <b>Reminder set!</b>\n\n"
        f"📅 <code>{when_raw}</code> UTC\n"
        f"📝 {text}",
        parse_mode="HTML"
    )


async def remind_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
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
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM reminders WHERE user_id = ? AND id = ?",
            (update.effective_user.id, reminder_id),
        )
    jobs = context.application.job_queue.get_jobs_by_name(f"reminder_{reminder_id}")
    for job in jobs:
        job.schedule_removal()
    if result.rowcount:
        await update.message.reply_text("✅ <b>Reminder canceled!</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Reminder not found.</b>", parse_mode="HTML")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    user_id = update.effective_user.id
    user_dir = ensure_user_dir(user_id)
    saved_path: Path | None = None

    if update.message.document:
        doc = update.message.document
        file = await doc.get_file()
        safe_name = doc.file_name or f"file_{doc.file_unique_id}"
        saved_path = user_dir / safe_name
        await file.download_to_drive(saved_path)

    elif update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        saved_path = user_dir / f"photo_{photo.file_unique_id}.jpg"
        await file.download_to_drive(saved_path)

    if saved_path:
        context.user_data["last_file"] = str(saved_path)
        await update.message.reply_text(
            f"✅ <b>File saved!</b>\n\n"
            f"📁 <code>{saved_path.name}</code>\n\n"
            f"Use <code>/files_list</code> to view all files or <code>/convert_png</code> <code>/convert_jpg</code> to convert images.",
            parse_mode="HTML"
        )


async def files_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    user_dir = ensure_user_dir(update.effective_user.id)
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
    target = user_dir / name
    if not target.exists():
        await update.message.reply_text(
            "❌ <b>File not found.</b>\n\n"
            "Use <code>/files_list</code> to see available files.",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text("📤 <b>Sending file...</b>", parse_mode="HTML")
    await update.message.reply_document(document=InputFile(target))


def is_image(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


async def convert_image(update: Update, context: ContextTypes.DEFAULT_TYPE, fmt: str) -> None:
    upsert_user(update)
    last_file = context.user_data.get("last_file")
    if not last_file:
        await update.message.reply_text(
            "❌ <b>No image found.</b>\n\n"
            "Send an image first, then run <code>/convert_png</code> or <code>/convert_jpg</code>.",
            parse_mode="HTML"
        )
        return
    src = Path(last_file)
    if not src.exists() or not is_image(src):
        await update.message.reply_text(
            "❌ <b>Last file is not an image.</b>\n\n"
            "Please send a valid image file.",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text(f"🔄 <b>Converting to {fmt.upper()}...</b>", parse_mode="HTML")
    out_path = src.with_suffix(f".{fmt}")
    with Image.open(src) as img:
        img.save(out_path, format=fmt.upper())
    context.user_data["last_file"] = str(out_path)
    await update.message.reply_text(
        f"✅ <b>Conversion complete!</b>\n\n📄 <code>{out_path.name}</code>",
        parse_mode="HTML"
    )
    await update.message.reply_document(document=InputFile(out_path))


async def convert_png(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await convert_image(update, context, "png")


async def convert_jpg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await convert_image(update, context, "jpg")


async def qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upsert_user(update)
    text = parse_args_text(context)
    if not text:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/qr &lt;text or url&gt;</code>\n\n"
            "<b>Example:</b> <code>/qr https://github.com</code>",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text("🔄 <b>Generating QR code...</b>", parse_mode="HTML")
    img = qrcode.make(text)
    out_path = DATA_DIR / f"qr_{update.effective_user.id}.png"
    img.save(out_path)
    await update.message.reply_text("✅ <b>QR code generated!</b>", parse_mode="HTML")
    await update.message.reply_document(document=InputFile(out_path))


def schedule_pending_reminders(app: Application) -> None:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, user_id, remind_at, text FROM reminders"
        ).fetchall()
    for row in rows:
        remind_at = dt.datetime.fromisoformat(row["remind_at"])
        if remind_at < now_utc():
            continue
        schedule_reminder(app, row["id"], row["user_id"], row["text"], remind_at)


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    if not API_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in .env or environment variables.")

    init_dirs()
    init_db()

    app = Application.builder().token(API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(CommandHandler("rss_add", rss_add))
    app.add_handler(CommandHandler("rss_list", rss_list))
    app.add_handler(CommandHandler("rss_remove", rss_remove))
    app.add_handler(CommandHandler("rss_latest", rss_latest))

    app.add_handler(CommandHandler("task_add", task_add))
    app.add_handler(CommandHandler("task_list", task_list))
    app.add_handler(CommandHandler("task_done", task_done))

    app.add_handler(CommandHandler("remind_add", remind_add))
    app.add_handler(CommandHandler("remind_list", remind_list))
    app.add_handler(CommandHandler("remind_cancel", remind_cancel))

    app.add_handler(CommandHandler("files_list", files_list))
    app.add_handler(CommandHandler("files_get", files_get))
    app.add_handler(CommandHandler("convert_png", convert_png))
    app.add_handler(CommandHandler("convert_jpg", convert_jpg))

    app.add_handler(CommandHandler("qr", qr_code))

    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))

    schedule_pending_reminders(app)
    app.run_polling()


if __name__ == "__main__":
    main()
