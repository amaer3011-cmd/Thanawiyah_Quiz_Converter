# -*- coding: utf-8 -*-
"""
توليد صور SVG توضيحية بسيطة لبعض أسئلة الكويز، باستخدام Gemini.

فكرة التصميم:
- quiz_generator.py بيطلب من Gemini، ضمن نفس استجابة توليد الأسئلة، حقل
  إضافي خفيف الحجم "needs_image" (true/false) لكل سؤال — بيحدد هل السؤال
  ده يستفيد فعليًا من رسم توضيحي (مخطط، شكل هندسي، رسم بياني بسيط) ولا لأ.
- بعد نجاح توليد وتصحيح الأسئلة (JSON) بالكامل، بنعمل استدعاء *منفصل*
  لـ Gemini لكل سؤال معلَّم بـ needs_image=True (بحد أقصى MAX_IMAGES_PER_QUIZ)
  عشان يولّد لنا SVG بسيط لموضوع السؤال.
- ليه استدعاء منفصل ومش جوه نفس الـ JSON؟ عشان لو رجّع SVG غير صالح أو
  فشل الاستدعاء، الحادثة دي تتعزل تمامًا عن نص الأسئلة نفسها، فمفيش خطر
  إن مشكلة في صورة واحدة تكسر الكويز كله أو حتى سؤال واحد فيه.
- الصورة الناتجة بتتحول لـ data URI (data:image/svg+xml;base64,...) وتتحط
  مباشرة في حقل imageUrl، فمفيش استضافة خارجية ولا روابط ممكن تنتهي.
"""
import re
import base64
import logging

from ai_router import get_router
import config

logger = logging.getLogger(__name__)

_SVG_TAG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)
_FORBIDDEN_PATTERNS_RE = re.compile(
    r"<script|javascript:|on\w+\s*=|<foreignObject|<iframe|xlink:href\s*=\s*[\"']https?:",
    re.IGNORECASE,
)

SVG_SYSTEM_PROMPT = """أنت مصمم رسوم توضيحية SVG بسيطة جدًا لأسئلة اختبارات تعليمية.

مهمتك: بناءً على نص سؤال وموضوعه، أنشئ رسمًا توضيحيًا SVG بسيطًا (أشكال
هندسية، أسهم، مخططات، تسميات نصية قصيرة) يساعد الطالب على تخيّل السؤال
بصريًا. لا تكتب حل السؤال أو الإجابة الصحيحة داخل الرسم إطلاقًا، ولا تكتب
نص السؤال نفسه بالكامل داخل الرسم.

قواعد إلزامية وصارمة:
- استخدم فقط الوسوم التالية: <svg>, <rect>, <circle>, <ellipse>, <line>,
  <path>, <polygon>, <polyline>, <text>, <tspan>, <g>, <defs>, <marker>.
  ممنوع منعًا باتًا: <script>, <foreignObject>, <iframe>, أي خاصية بادئة
  بـ "on" (مثل onclick)، وأي رابط خارجي (href لصورة أو ملف من الإنترنت).
- اكتب خاصية viewBox="0 0 400 260" بالضبط على وسم svg، وبدون خاصية width
  أو height صريحة عليه.
- الألوان: استخدم قيم hex واضحة وبسيطة (خلفية فاتحة أو بدون خلفية،
  ورسم بألوان مثل #1f2937, #2563eb, #dc2626, #16a34a, #f3f4f6).
- أي نص داخل الرسم يجب أن يكون قصيرًا جدًا وبنفس لغة السؤال.
- أعد فقط كود الـ SVG كاملاً بدءًا من <svg وحتى </svg>، بدون أي نص أو
  شرح أو علامات ```، وبدون أي تعليق قبله أو بعده.
"""


def _build_svg_prompt(question_text: str, topic: str) -> str:
    return (
        f"{SVG_SYSTEM_PROMPT}\n\n"
        f"موضوع السؤال: {topic or 'عام'}\n"
        f"نص السؤال: {question_text}\n\n"
        f"أنشئ الآن رسم SVG توضيحي واحد فقط مناسب لهذا السؤال."
    )


def _sanitize_svg(raw_text: str):
    """يتحقق من صلاحية وأمان الـ SVG الناتج، ويرجعه نظيفًا أو None لو غير صالح/غير آمن."""
    if not raw_text:
        return None
    text = raw_text.strip()
    text = re.sub(r"^```(?:svg|xml)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    match = _SVG_TAG_RE.search(text)
    if not match:
        return None
    svg = match.group(0)

    if _FORBIDDEN_PATTERNS_RE.search(svg):
        logger.warning("تم رفض SVG لاحتوائه على محتوى غير مسموح به (سكريبت/رابط خارجي).")
        return None

    if len(svg) > 20000:
        logger.warning("تم رفض SVG لأن حجمه أكبر من الحد المسموح.")
        return None

    return svg


def _svg_to_data_uri(svg: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def generate_svg_for_question(question_text: str, topic: str = ""):
    """يولّد صورة SVG واحدة لسؤال معيّن، ويرجع data URI جاهز أو None عند أي فشل."""
    prompt = _build_svg_prompt(question_text, topic)
    try:
        client = get_router()
        raw = client.generate(
            prompt,
            generation_config={"temperature": 0.5, "max_output_tokens": 2048},
        )
    except Exception as e:
        logger.warning(f"فشل مزود الذكاء لتوليد صورة SVG توضيحية: {e}")
        return None

    svg = _sanitize_svg(raw)
    if not svg:
        return None
    return _svg_to_data_uri(svg)


def attach_images_to_questions(questions: list, max_images: int = None) -> list:
    """
    يمر على الأسئلة المعلَّمة بـ needs_image=True (بحد أقصى max_images)
    ويحاول توليد صورة SVG توضيحية لكل واحد منها، ويحقنها في حقل imageUrl.

    أي فشل في توليد صورة لسؤال معين يُتجاهل بهدوء (يفضل السؤال بدون صورة)
    ولا يوقف أو يفشل باقي عملية توليد الكويز.
    """
    if not config.ENABLE_QUESTION_IMAGES:
        return questions

    limit = config.MAX_IMAGES_PER_QUIZ if max_images is None else max_images
    generated = 0

    for q in questions:
        if generated >= limit:
            break
        if not q.get("needs_image"):
            continue

        try:
            data_uri = generate_svg_for_question(q.get("question", ""), q.get("topic", ""))
        except Exception:
            logger.exception("خطأ غير متوقع أثناء توليد صورة توضيحية لسؤال — تم تجاهله.")
            data_uri = None

        if data_uri:
            q["imageUrl"] = data_uri
            generated += 1

    return questions
