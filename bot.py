# -*- coding: utf-8 -*-
"""Standalone Thanawiyah_Quiz converter bot."""
from __future__ import annotations
import asyncio, logging, os, uuid
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import config
from provided_quiz_parser import parse_provided_quiz
import html_builder

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
os.makedirs(config.TEMP_DIR, exist_ok=True)
HELP = """أرسل الأسئلة بهذا الشكل:

1) ما عاصمة مصر؟
أ) القاهرة
ب) الرباط
ج) دمشق
د) تونس
الإجابة: أ
التفسير: القاهرة هي عاصمة جمهورية مصر العربية.

يجب أن يحتوي كل سؤال على أربعة خيارات. يمكنك إرسال النص مباشرة أو ملف TXT/MD، وسيتم تحويله إلى HTML بنفس تصميم Thanawiyah_Quiz🎯."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلًا بك في Thanawiyah_Quiz🎯\n\nأرسل محتوى الأسئلة مع الخيارات والإجابات والتفسيرات وسأحوّله مباشرة إلى كويز HTML.\n\n" + HELP)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)

def build_file(questions):
    path=os.path.join(config.TEMP_DIR, f"quiz_{uuid.uuid4().hex}.html")
    html_builder.save_quiz_html(questions, path, exam_title="كويز مخصص", exam_type="open", duration_minutes=config.DEFAULT_DURATION_MINUTES, auto_start=True)
    return path

def remove(path):
    try: os.remove(path)
    except OSError: pass

async def send_quiz(update, questions):
    path=await asyncio.to_thread(build_file, questions)
    try:
        with open(path, "rb") as f:
            await update.message.reply_document(f, filename="Thanawiyah_Quiz.html", caption=f"✅ تم تحويل {len(questions)} سؤالًا. افتح الملف وابدأ مباشرة.")
    finally: remove(path)

async def convert_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        questions=await asyncio.to_thread(parse_provided_quiz, (update.message.text or "").strip())
        await send_quiz(update, questions)
    except ValueError as exc:
        await update.message.reply_text(f"❌ لم أستطع قراءة الأسئلة:\n{exc}\n\nاستخدم /help لرؤية الصيغة الصحيحة.")
    except Exception:
        logger.exception("Quiz conversion failed")
        await update.message.reply_text("❌ حدث خطأ أثناء إنشاء الملف. تأكد من صيغة النص وحاول مرة أخرى.")

async def convert_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc=update.message.document; name=(doc.file_name or "").lower()
    mime=(doc.mime_type or '').lower()
    is_text_file=name.endswith((".txt", ".md", ".markdown", ".mdown")) or mime in ('text/markdown','text/plain','text/x-markdown','application/markdown')
    if not is_text_file:
        await update.message.reply_text("❌ أرسل ملف TXT أو MD فقط، أو أرسل النص مباشرة."); return
    if doc.file_size and doc.file_size > config.MAX_FILE_SIZE:
        await update.message.reply_text("❌ الملف أكبر من الحد المسموح."); return
    source=os.path.join(config.TEMP_DIR, f"source_{uuid.uuid4().hex}")
    try:
        tg_file=await context.bot.get_file(doc.file_id); await tg_file.download_to_drive(source)
        with open(source, encoding="utf-8-sig", errors="replace") as fh:
            text=fh.read()
        if not text.strip():
            raise ValueError('الملف فارغ أو لا يحتوي على نص قابل للقراءة.')
        questions=await asyncio.to_thread(parse_provided_quiz, text)
        await send_quiz(update, questions)
    except ValueError as exc:
        await update.message.reply_text(f"❌ صيغة الملف غير مكتملة:\n{exc}")
    except Exception:
        logger.exception("Document conversion failed")
        await update.message.reply_text("❌ تعذر قراءة الملف. تأكد أنه UTF-8 ويحتوي على أسئلة منظمة.")
    finally: remove(source)

def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("ضع TELEGRAM_BOT_TOKEN في Environment Variables")
    app=Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.Document.ALL, convert_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, convert_text))
    logger.info("Thanawiyah_Quiz_Converter is running")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__": main()
