# -*- coding: utf-8 -*-
"""
استخراج المحتوى النصي التعليمي من مصادر مختلفة:
- روابط يوتيوب (عبر Transcript API)
- ملفات صوتية (عبر Gemini الصوتي)
- صور (عبر Gemini Vision)
- ملفات PDF (استخراج نص)
- ملفات HTML (استخراج نص من الوسوم)

كل دالة ترجع dict بالشكل:
{"success": bool, "text": str, "source_type": str, "error": str|None}
"""
import os
import re
import logging
import requests
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
import pdfplumber
import config
from gemini_client import get_client

logger = logging.getLogger(__name__)

YOUTUBE_REGEX = re.compile(
    r"(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{11})"
)


def is_youtube_url(text: str) -> bool:
    return bool(YOUTUBE_REGEX.search(text or ""))


def extract_youtube_video_id(url: str) -> str | None:
    match = YOUTUBE_REGEX.search(url)
    if match:
        return match.group(1)
    # محاولة إضافية عبر parse_qs
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
    except Exception:
        pass
    return None


def get_youtube_transcript(url: str) -> dict:
    """يجلب الترجمة حصريًا عبر TranscriptAPI.com، مع دعم العربي والإنجليزي وASR."""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return {"success": False, "text": "", "source_type": "youtube", "error": "رابط يوتيوب غير صحيح."}
    api_key = config.TRANSCRIPT_API_KEY
    if not api_key:
        return {"success": False, "text": "", "source_type": "youtube",
                "error": "مفتاح TranscriptAPI غير مضبوط. أضف TRANSCRIPT_API_KEY في إعدادات الحاوية."}
    try:
        response = requests.get(
            f"{config.TRANSCRIPT_API_BASE}/youtube/transcript",
            params={"video_url": url, "format": "json", "include_timestamp": "false",
                    "language": "ar,en,asr"},
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=config.TRANSCRIPT_API_TIMEOUT,
        )
        if response.status_code == 404:
            return {"success": False, "text": "", "source_type": "youtube",
                    "error": "TranscriptAPI لم يجد ترجمة متاحة لهذا الفيديو. تأكد أن الفيديو عام ويحتوي على captions."}
        if response.status_code in (401, 403):
            return {"success": False, "text": "", "source_type": "youtube",
                    "error": "مفتاح TranscriptAPI غير صالح أو غير مفعّل لهذه العملية."}
        response.raise_for_status()
        payload = response.json()
        segments = payload.get("transcript", []) if isinstance(payload, dict) else []
        if isinstance(segments, list):
            full_text = " ".join(str(x.get("text", "")) for x in segments if isinstance(x, dict))
        else:
            full_text = str(segments or (payload.get("text", "") if isinstance(payload, dict) else payload))
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if not full_text:
            return {"success": False, "text": "", "source_type": "youtube", "error": "وصل رد فارغ من TranscriptAPI."}
        return {"success": True, "text": full_text, "source_type": "youtube", "error": None}
    except requests.Timeout:
        return {"success": False, "text": "", "source_type": "youtube", "error": "انتهت مهلة الاتصال بـ TranscriptAPI. حاول مرة أخرى."}
    except requests.RequestException as exc:
        logger.exception("TranscriptAPI request failed")
        return {"success": False, "text": "", "source_type": "youtube", "error": f"تعذر الاتصال بـ TranscriptAPI: {exc}"}
    except Exception as exc:
        logger.exception("Unexpected TranscriptAPI response")
        return {"success": False, "text": "", "source_type": "youtube", "error": f"خطأ في قراءة رد TranscriptAPI: {exc}"}


def extract_from_pdf(file_path: str) -> dict:
    try:
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)
        full_text = "\n".join(text_parts).strip()
        if not full_text:
            return {"success": False, "text": "", "source_type": "pdf",
                    "error": "لم أستطع استخراج نص من هذا الـ PDF (قد يكون صورة ممسوحة ضوئيًا بدون نص)."}
        return {"success": True, "text": full_text, "source_type": "pdf", "error": None}
    except Exception as e:
        logger.exception("خطأ في استخراج PDF")
        return {"success": False, "text": "", "source_type": "pdf",
                "error": f"تعذّرت قراءة ملف الـ PDF: {e}"}


def extract_from_html(file_path: str) -> dict:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
        soup = BeautifulSoup(raw, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()

        if not text:
            return {"success": False, "text": "", "source_type": "html",
                    "error": "ملف الـ HTML لا يحتوي على نص قابل للقراءة."}
        return {"success": True, "text": text, "source_type": "html", "error": None}
    except Exception as e:
        logger.exception("خطأ في استخراج HTML")
        return {"success": False, "text": "", "source_type": "html",
                "error": f"تعذّرت قراءة ملف الـ HTML: {e}"}


def extract_from_image(file_path: str) -> dict:
    """يستخدم Gemini Vision لقراءة وفهم محتوى الصورة (نص/معادلات/رسوم)."""
    try:
        with open(file_path, "rb") as f:
            image_bytes = f.read()

        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        prompt = (
            "استخرج كل المحتوى التعليمي الموجود في هذه الصورة بدقة تامة: "
            "النصوص، المعادلات، القوانين، الرسوم البيانية ومكوناتها، الجداول. "
            "اكتب النتيجة كنص واضح ومنظم يحافظ على المعنى العلمي الكامل، "
            "بنفس اللغة الظاهرة في الصورة (عربي أو إنجليزي)."
        )

        client = get_client()
        result_text = client.generate_from_media(
            prompt,
            [{"mime_type": mime_type, "data": image_bytes}]
        )

        if not result_text or not result_text.strip():
            return {"success": False, "text": "", "source_type": "image",
                    "error": "لم أستطع استخراج أي محتوى مفهوم من الصورة."}

        return {"success": True, "text": result_text.strip(), "source_type": "image", "error": None}
    except Exception as e:
        logger.exception("خطأ في تحليل الصورة عبر Gemini")
        return {"success": False, "text": "", "source_type": "image",
                "error": f"تعذّر تحليل الصورة: {e}"}


def extract_from_audio(file_path: str) -> dict:
    """يستخدم Gemini لتفريغ وتحليل ملف صوتي مباشرة (رفع الملف وتمريره كوسائط)."""
    import google.generativeai as genai
    import config
    from gemini_client import _gemini_call_lock

    last_error = None
    for key in config.GEMINI_API_KEYS:
        uploaded_file = None
        try:
            # نفس القفل المستخدم في gemini_client لمنع تعارض تهيئة المفتاح
            # (genai.configure) مع طلبات متزامنة من مستخدمين آخرين.
            with _gemini_call_lock:
                genai.configure(api_key=key)
                uploaded_file = genai.upload_file(file_path)

                prompt = (
                    "استمع إلى هذا التسجيل الصوتي بعناية، وفرّغه إلى نص كامل، "
                    "ثم لخّص المحتوى التعليمي الأساسي فيه (الأفكار، القواعد، الأمثلة) "
                    "بنفس اللغة المستخدمة في التسجيل (عربي أو إنجليزي)، بشكل واضح ومنظم."
                )
                model = genai.GenerativeModel(config.GEMINI_TEXT_MODEL)
                response = model.generate_content([prompt, uploaded_file])

            if response and getattr(response, "text", None):
                return {"success": True, "text": response.text.strip(),
                        "source_type": "audio", "error": None}
            else:
                raise ValueError("استجابة فارغة")
        except Exception as e:
            last_error = e
            logger.warning(f"فشل مفتاح أثناء معالجة الصوت: {e}")
            continue
        finally:
            # نمسح الملف المرفوع من Gemini File API فورًا بعد الاستخدام،
            # عشان الملفات متتراكمش على حساب الـ API بدون داعي.
            if uploaded_file is not None:
                try:
                    genai.delete_file(uploaded_file.name)
                except Exception:
                    logger.warning("تعذّر مسح الملف الصوتي المرفوع من Gemini File API.")

    return {"success": False, "text": "", "source_type": "audio",
            "error": f"تعذّر تحليل الملف الصوتي عبر كل المفاتيح المتاحة: {last_error}"}
