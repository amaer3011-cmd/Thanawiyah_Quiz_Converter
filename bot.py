# -*- coding: utf-8 -*-
"""
بوت تليجرام لتوليد كويزات تعليمية من مصادر متعددة:
رابط يوتيوب، ملف صوتي، صورة، PDF، أو ملف HTML.

الاستخدام:
    python bot.py
"""
import os
import re
import logging
import asyncio
import itertools
import tempfile
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from telegram.request import HTTPXRequest

import config
import content_extractor
import quiz_generator
import html_builder
from store import store
from provided_quiz_parser import parse_provided_quiz, looks_like_provided_quiz

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# حالات المحادثة
(
    WAITING_SOURCE,
    WAITING_CONTENT_CONFIRM,
    WAITING_CONTENT_EDIT,
    WAITING_QUESTION_COUNT,
    WAITING_EXAM_TYPE,
    WAITING_DURATION,
) = range(6)

os.makedirs(config.TEMP_DIR, exist_ok=True)

# قفل بسيط لكل مستخدم (chat_id) يمنعه من إطلاق أكتر من عملية توليد/تحليل
# تقيلة (استدعاء Gemini) في نفس الوقت — يحمي الكوتة المشتركة بين المستخدمين
# ويمنع تعارض حالة المحادثة (context.user_data) لنفس المستخدم لو بعت رسايل
# سريعة فوق بعض.
_active_users: set = set()

_MARKDOWN_V1_SPECIAL_CHARS = re.compile(r"([_*`\[])")


def _escape_markdown_v1(text: str) -> str:
    """
    ينظّف نص حر (مستخرج من مصدر خارجي زي PDF/HTML) من رموز legacy Markdown
    (_ * ` [) قبل حقنه جوه رسالة بـ parse_mode="Markdown"، عشان تليجرام
    منيرفضش الرسالة بخطأ "Can't parse entities" ويكسر تدفق المحادثة.
    """
    if not text:
        return text
    return _MARKDOWN_V1_SPECIAL_CHARS.sub(r"\\\1", text)


# ---------------------------------------------------------------------------
# أوامر أساسية
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        store.upsert_user(update.effective_user.id, update.effective_user.username or update.effective_user.full_name or '')
    context.user_data.clear()
    welcome = (
        "👋 أهلًا بيك في *بوت الكويزات التعليمية*!\n\n"
        "ابعتلي أي مصدر تعليمي وهعملّك منه كويز تفاعلي كامل:\n"
        "📺 رابط فيديو يوتيوب\n"
        "🎧 ملف صوتي (محاضرة/شرح)\n"
        "🖼️ صورة (سؤال، رسم، صفحة كتاب)\n"
        "📄 ملف PDF\n"
        "🌐 ملف HTML\n\n"
        "هحلل المحتوى، أفهم الموضوع، وأجهّزلك أسئلة اختيار من متعدد "
        "بتعتمد على *الفهم والتحليل والاستنتاج* — مش الحفظ بس.\n\n"
        "ابعتلي المصدر دلوقتي عشان نبدأ 🚀"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")
    return WAITING_SOURCE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم الإلغاء. ابعت /start لو عاوز تبدأ من جديد.")
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "الأوامر المتاحة:\n"
        "/start — ابدأ كويز جديد\n"
        "/cancel — إلغاء العملية الحالية\n"
        "/help — عرض هذه الرسالة"
    )


# ---------------------------------------------------------------------------
# استقبال المصدر (رابط / ملف)
# ---------------------------------------------------------------------------

async def handle_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """غلاف (wrapper) بيحمي من تشغيل أكتر من عملية تحليل لنفس المستخدم في
    نفس الوقت، ويضمن تحرير القفل دايمًا حتى لو حصل استثناء غير متوقع."""
    chat_id = update.effective_chat.id
    if chat_id in _active_users:
        await update.message.reply_text(
            "⏳ لسه بحلل مصدرك السابق، استنى شوية لحد ما أخلّص قبل ما تبعت حاجة تانية."
        )
        return WAITING_SOURCE
    _active_users.add(chat_id)
    try:
        return await _handle_source_impl(update, context)
    finally:
        _active_users.discard(chat_id)


async def _handle_source_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = (message.text or "").strip()

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    extraction_result = None

    try:
        # 0) نص أسئلة جاهز من المستخدم: لا نرسله إلى الذكاء الاصطناعي.
        if text and looks_like_provided_quiz(text):
            try:
                questions = parse_provided_quiz(text)
            except ValueError as exc:
                await message.reply_text(f"❌ صيغة الأسئلة غير مكتملة: {exc}\n\nأرسل /help لرؤية النموذج الصحيح.")
                return WAITING_SOURCE
            output_path = os.path.join(config.TEMP_DIR, f"provided_quiz_{uuid.uuid4().hex}.html")
            try:
                html_builder.save_quiz_html(
                    questions, output_path, exam_title="كويز مخصص",
                    exam_type="open", duration_minutes=config.DEFAULT_DURATION_MINUTES,
                    auto_start=True,
                )
                with open(output_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id, document=f, filename="quiz.html",
                        caption=f"✅ تم تحويل {len(questions)} سؤالًا إلى كويز جاهز بنفس تصميم Thanawiyah_Quiz🎯.\nافتح الملف وابدأ مباشرة."
                    )
            finally:
                _cleanup(output_path)
            context.user_data.clear()
            return WAITING_SOURCE

        # 1) رابط يوتيوب
        if text and content_extractor.is_youtube_url(text):
            status_msg = await message.reply_text("📺 بجيب النص من الفيديو... لحظات.")
            extraction_result = content_extractor.get_youtube_transcript(text)
            await status_msg.delete()

        # 2) صورة
        elif message.photo:
            status_msg = await message.reply_text("🖼️ بحلل الصورة وبفهم محتواها...")
            photo = message.photo[-1]  # أعلى دقة
            file = await context.bot.get_file(photo.file_id)
            local_path = os.path.join(config.TEMP_DIR, f"{uuid.uuid4().hex}.jpg")
            await file.download_to_drive(local_path)
            # استدعاء Gemini بيحصل بشكل sync/blocking داخل content_extractor؛
            # نشغّله في thread منفصل عشان مايجمّدش حلقة الأحداث (event loop)
            # ويمنع البوت من التجمّد لباقي المستخدمين أثناء التحليل.
            extraction_result = await asyncio.to_thread(
                content_extractor.extract_from_image, local_path
            )
            _cleanup(local_path)
            await status_msg.delete()

        # 3) مستند (PDF / HTML / صورة كمستند / صوت كمستند)
        elif message.document:
            doc = message.document
            file_name = (doc.file_name or "").lower()

            if doc.file_size and doc.file_size > config.MAX_FILE_SIZE:
                await message.reply_text("⚠️ الملف أكبر من الحد المسموح به (20MB). ابعت ملف أصغر من فضلك.")
                return WAITING_SOURCE

            status_msg = await message.reply_text("📄 بقرأ الملف...")
            file = await context.bot.get_file(doc.file_id)
            suffix = os.path.splitext(file_name)[1] or ""
            local_path = os.path.join(config.TEMP_DIR, f"{uuid.uuid4().hex}{suffix}")
            await file.download_to_drive(local_path)

            if file_name.endswith(".pdf"):
                extraction_result = await asyncio.to_thread(
                    content_extractor.extract_from_pdf, local_path
                )
            elif file_name.endswith((".html", ".htm")):
                extraction_result = await asyncio.to_thread(
                    content_extractor.extract_from_html, local_path
                )
            elif file_name.endswith((".jpg", ".jpeg", ".png", ".webp")):
                extraction_result = await asyncio.to_thread(
                    content_extractor.extract_from_image, local_path
                )
            elif file_name.endswith((".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac")):
                base_text = "🎧 بستمع للملف الصوتي وبفرّغه... ممكن ياخد شوية وقت."
                await status_msg.edit_text(base_text)
                extraction_result = await _run_with_progress(
                    status_msg,
                    asyncio.to_thread(content_extractor.extract_from_audio, local_path),
                    base_text,
                )
            else:
                await status_msg.delete()
                await message.reply_text(
                    "⚠️ صيغة الملف دي مش مدعومة. الصيغ المدعومة: PDF, HTML, صور, وملفات صوتية."
                )
                _cleanup(local_path)
                return WAITING_SOURCE

            _cleanup(local_path)
            await status_msg.delete()

        # 4) صوت مُرسل كرسالة صوتية (voice) أو audio
        elif message.voice or message.audio:
            base_text = "🎧 بستمع للتسجيل الصوتي وبفرّغه... ممكن ياخد شوية وقت."
            status_msg = await message.reply_text(base_text)
            media = message.voice or message.audio
            file = await context.bot.get_file(media.file_id)
            local_path = os.path.join(config.TEMP_DIR, f"{uuid.uuid4().hex}.ogg")
            await file.download_to_drive(local_path)
            extraction_result = await _run_with_progress(
                status_msg,
                asyncio.to_thread(content_extractor.extract_from_audio, local_path),
                base_text,
            )
            _cleanup(local_path)
            await status_msg.delete()

        else:
            await message.reply_text(
                "ابعتلي رابط يوتيوب، أو ملف (PDF/HTML/صورة/صوت) عشان أقدر أعملّك كويز منه 🙏"
            )
            return WAITING_SOURCE

    except Exception as e:
        logger.exception("خطأ أثناء معالجة المصدر")
        await message.reply_text(
            "⚠️ حصل خطأ غير متوقع أثناء معالجة المصدر. جرّب تاني أو ابعت /start من جديد."
        )
        return WAITING_SOURCE

    if not extraction_result or not extraction_result.get("success"):
        error_msg = extraction_result.get("error") if extraction_result else "خطأ غير معروف."
        await message.reply_text(f"❌ {error_msg}\n\nجرّب مصدر تاني أو تأكد من الرابط/الملف.")
        return WAITING_SOURCE

    content_text = extraction_result["text"]
    context.user_data["content_text"] = content_text
    context.user_data["source_type"] = extraction_result["source_type"]
    context.user_data.pop("extra_instructions", None)

    preview = _escape_markdown_v1(content_text[:300].strip())
    await message.reply_text(
        f"✅ تم استخراج المحتوى بنجاح ({len(content_text)} حرف تقريبًا).\n\n"
        f"*مقتطف:*\n_{preview}..._\n\n"
        f"عايز نكمل بالمحتوى ده زي ما هو، ولا حابب تضيف أو تصحح حاجة قبل توليد الأسئلة؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ متابعة والتوليد", callback_data="content_continue")],
            [InlineKeyboardButton("✏️ عدّل/أضف على المحتوى", callback_data="content_edit")],
        ])
    )
    return WAITING_CONTENT_CONFIRM


def _cleanup(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


async def _run_with_progress(status_msg, awaitable, base_text: str, interval: float = 7.0):
    """
    يشغّل عملية طويلة (زي تفريغ ملف صوتي) مع تحديث رسالة الحالة دوريًا
    (كل interval ثانية) بمؤشر تقدّم تقريبي ونقط متحركة، عشان المستخدم يحس
    إن في شغل مستمر بدل ما يفضل شايف نفس الرسالة الثابتة لدقيقة أو أكتر.

    ملحوظة: النسبة المئوية تقريبية بحتة (مبنية على وقت منقضي مفترض وليست
    نسبة حقيقية من تقدم المعالجة الفعلي داخل Gemini)، ومسقوفة عند 90% لحد
    ما العملية تخلص فعليًا، عشان منديش انطباع كاذب بالاكتمال.
    """
    task = asyncio.ensure_future(awaitable)
    dots_cycle = itertools.cycle(["", ".", "..", "..."])
    elapsed = 0.0

    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=interval)
        except asyncio.TimeoutError:
            elapsed += interval
            approx_pct = min(90, int(elapsed / 90 * 90))
            try:
                await status_msg.edit_text(
                    f"{base_text}\n"
                    f"⏱️ الوقت المنقضي تقريبًا: {int(elapsed)} ثانية — لسه شغال{next(dots_cycle)} (~{approx_pct}%)"
                )
            except Exception:
                # فشل تعديل الرسالة (زي "لم يتغير المحتوى") مش خطأ يستحق
                # إيقاف العملية الأساسية، فبنكمل بهدوء.
                pass
        except Exception:
            break

    return await task


# ---------------------------------------------------------------------------
# خطوة تأكيد/تعديل المحتوى قبل التوليد
# ---------------------------------------------------------------------------

async def handle_content_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "content_edit":
        await query.message.reply_text(
            "تمام، ابعتلي أي إضافة أو تصحيح تحب تضيفه على المحتوى قبل توليد "
            "الأسئلة (مثلاً: \"ركّز أكتر على الجزء الخاص بكذا\"، أو تصحيح "
            "معلومة غلط، أو نص إضافي عايز يتضاف).\n\n"
            "لو مش عايز تضيف حاجة، ابعت /skip للمتابعة عادي."
        )
        return WAITING_CONTENT_EDIT

    return await _ask_question_count(query.message, context)


async def handle_content_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text:
        existing = context.user_data.get("extra_instructions", "")
        context.user_data["extra_instructions"] = (existing + "\n" + text).strip()
        await update.message.reply_text("تمام 👍 هاخد ده في الاعتبار وقت توليد الأسئلة.")
    return await _ask_question_count(update.message, context)


async def handle_content_edit_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _ask_question_count(update.message, context)


# ---------------------------------------------------------------------------
# اختيار عدد الأسئلة
# ---------------------------------------------------------------------------

async def _ask_question_count(message, context: ContextTypes.DEFAULT_TYPE):
    await message.reply_text(
        f"كام سؤال عاوز الكويز يكون فيه؟ (من {config.MIN_QUESTIONS} إلى {config.MAX_QUESTIONS})\n"
        f"ابعت رقم، أو دوس على أحد الاختيارات:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("10", callback_data="qcount_10"),
             InlineKeyboardButton("15", callback_data="qcount_15"),
             InlineKeyboardButton("20", callback_data="qcount_20")],
            [InlineKeyboardButton("30", callback_data="qcount_30")],
        ])
    )
    return WAITING_QUESTION_COUNT


async def handle_question_count_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("من فضلك ابعت رقم صحيح لعدد الأسئلة.")
        return WAITING_QUESTION_COUNT

    num = int(text)
    if num < config.MIN_QUESTIONS or num > config.MAX_QUESTIONS:
        await update.message.reply_text(
            f"العدد لازم يكون بين {config.MIN_QUESTIONS} و {config.MAX_QUESTIONS}."
        )
        return WAITING_QUESTION_COUNT

    context.user_data["num_questions"] = num
    return await _ask_exam_type(update.message, context)


async def handle_question_count_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    num = int(query.data.split("_")[1])
    context.user_data["num_questions"] = num
    return await _ask_exam_type(query.message, context)


async def _ask_exam_type(message, context: ContextTypes.DEFAULT_TYPE):
    await message.reply_text(
        "تمام 👍 وعاوز الامتحان يكون؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 مفتوح (بدون وقت)", callback_data="exam_open")],
            [InlineKeyboardButton("⏳ مؤقت", callback_data="exam_timed")],
        ])
    )
    return WAITING_EXAM_TYPE


# ---------------------------------------------------------------------------
# اختيار نوع الامتحان، ثم مدته لو مؤقت، ثم توليد الكويز فعليًا
# ---------------------------------------------------------------------------

async def handle_exam_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "exam_open":
        context.user_data["exam_type"] = "open"
        context.user_data["duration_minutes"] = config.DEFAULT_DURATION_MINUTES
        return await _run_generation_guarded(update, context)

    # exam_timed → نسأل عن المدة قبل ما نبدأ التوليد
    context.user_data["exam_type"] = "timed"
    await query.message.reply_text(
        "تمام، الامتحان هيكون بوقت محدد. عاوز مدته كام دقيقة؟\n"
        f"(تقدر تكتب رقم من {config.MIN_DURATION_MINUTES} إلى {config.MAX_DURATION_MINUTES}، أو تدوس على اختيار جاهز)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("5", callback_data="duration_5"),
             InlineKeyboardButton("10", callback_data="duration_10"),
             InlineKeyboardButton("15", callback_data="duration_15")],
            [InlineKeyboardButton("20", callback_data="duration_20"),
             InlineKeyboardButton("30", callback_data="duration_30"),
             InlineKeyboardButton("45", callback_data="duration_45")],
        ])
    )
    return WAITING_DURATION


async def handle_duration_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    minutes = int(query.data.split("_")[1])
    context.user_data["duration_minutes"] = minutes
    return await _run_generation_guarded(update, context)


async def handle_duration_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("من فضلك ابعت رقم صحيح لعدد دقائق الامتحان.")
        return WAITING_DURATION

    minutes = int(text)
    if minutes < config.MIN_DURATION_MINUTES or minutes > config.MAX_DURATION_MINUTES:
        await update.message.reply_text(
            f"المدة لازم تكون بين {config.MIN_DURATION_MINUTES} و {config.MAX_DURATION_MINUTES} دقيقة."
        )
        return WAITING_DURATION

    context.user_data["duration_minutes"] = minutes
    return await _run_generation_guarded(update, context)


async def _run_generation_guarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """غلاف بيحمي من إطلاق أكتر من عملية توليد لنفس المستخدم في نفس الوقت."""
    chat_id = update.effective_chat.id
    if chat_id in _active_users:
        if update.callback_query:
            await update.callback_query.answer(
                "⏳ لسه بجهّز كويز سابق، استنى شوية.", show_alert=True
            )
        else:
            await update.message.reply_text("⏳ لسه بجهّز كويز سابق، استنى شوية.")
        return WAITING_EXAM_TYPE
    _active_users.add(chat_id)
    try:
        return await _generate_and_send_quiz(update, context)
    finally:
        _active_users.discard(chat_id)


async def _generate_and_send_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat_id = update.effective_chat.id
    exam_type = context.user_data.get("exam_type", "open")
    duration_minutes = context.user_data.get("duration_minutes", config.DEFAULT_DURATION_MINUTES)

    status_msg = await message.reply_text(
        "🧠 بحلل المحتوى وبفكر في أفضل أسئلة تختبر فهمك... ممكن ياخد نص دقيقة لدقيقة."
    )

    content_text = context.user_data.get("content_text")
    num_questions = context.user_data.get("num_questions", config.DEFAULT_QUESTIONS)
    extra_instructions = context.user_data.get("extra_instructions", "")

    if not content_text:
        await status_msg.edit_text("⚠️ حصل خطأ: المحتوى ضاع. ابعت /start من جديد من فضلك.")
        return ConversationHandler.END

    result = await asyncio.to_thread(
        quiz_generator.generate_quiz_questions,
        content_text,
        num_questions=num_questions,
        extra_instructions=extra_instructions,
    )

    if not result.get("success"):
        await status_msg.edit_text(
            f"❌ فشل توليد الأسئلة: {result.get('error')}\n\n"
            f"ابعت /start عشان تجرب تاني."
        )
        return ConversationHandler.END

    questions = result["questions"]
    quiz_id = store.save_quiz(chat_id, context.user_data.get('topic', 'Quiz'), questions)
    context.user_data['quiz_id'] = quiz_id

    try:
        output_path = os.path.join(config.TEMP_DIR, f"quiz_{uuid.uuid4().hex}.html")
        html_builder.save_quiz_html(
            questions,
            output_path,
            exam_type=exam_type,
            duration_minutes=duration_minutes,
            auto_start=True,
        )

        await status_msg.edit_text(f"✅ تم توليد {len(questions)} سؤال بنجاح! بجهّز الملف...")

        with open(output_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="quiz.html",
                caption=(
                    f"🎯 كويزك جاهز! ({len(questions)} سؤال)\n\n"
                    "افتح الملف في أي متصفح وابدأ الاختبار مباشرة.\n"
                    "هيظهرلك تفسير لكل إجابة صح أو غلط بعد التسليم.\n\n"
                    "عاوز كويز تاني؟ ابعت /start"
                )
            )
        _cleanup(output_path)

    except Exception as e:
        logger.exception("خطأ أثناء بناء أو إرسال ملف الكويز")
        await status_msg.edit_text(
            "⚠️ حصل خطأ أثناء تجهيز الملف. جرّب تاني بابعت /start، ولو المشكلة استمرت "
            "بلّغ المسؤول عن البوت."
        )

    context.user_data.clear()
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------

def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "❌ لم يتم ضبط TELEGRAM_BOT_TOKEN في ملف .env. أضفه ثم أعد المحاولة."
        )
    if not config.GEMINI_API_KEYS:
        raise SystemExit(
            "❌ لم يتم ضبط أي مفتاح في GEMINI_API_KEYS في ملف .env. أضف مفتاحًا واحدًا على الأقل."
        )

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        # تليجرام (مش Gemini) بيحتاج مهلات أطول من الافتراضي، خصوصًا وقت
        # رفع/تنزيل ملفات صوتية كبيرة أو انتظار رد أثناء تعديل رسائل الحالة
        # المتكررة. الاستدعاءات الفعلية لـ Gemini بقت شغالة في threads
        # منفصلة (asyncio.to_thread) فمبتحجزش حلقة الأحداث أصلًا.
        .request(HTTPXRequest(connect_timeout=20.0, read_timeout=60.0,
                               write_timeout=60.0, pool_timeout=20.0))
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_SOURCE: [
                MessageHandler(
                    (filters.TEXT & ~filters.COMMAND) | filters.PHOTO |
                    filters.Document.ALL | filters.VOICE | filters.AUDIO,
                    handle_source
                ),
            ],
            WAITING_CONTENT_CONFIRM: [
                CallbackQueryHandler(handle_content_confirm, pattern=r"^content_"),
            ],
            WAITING_CONTENT_EDIT: [
                CommandHandler("skip", handle_content_edit_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_content_edit_text),
            ],
            WAITING_QUESTION_COUNT: [
                CallbackQueryHandler(handle_question_count_button, pattern=r"^qcount_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question_count_text),
            ],
            WAITING_EXAM_TYPE: [
                CallbackQueryHandler(handle_exam_type_choice, pattern=r"^exam_"),
            ],
            WAITING_DURATION: [
                CallbackQueryHandler(handle_duration_button, pattern=r"^duration_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_duration_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    logger.info("🚀 البوت شغّال الآن (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
