# -*- coding: utf-8 -*-
"""
يبني ملف HTML نهائي للكويز عبر حقن الأسئلة داخل نفس قالب
Thanawiyah_Quiz🎯 الأصلي (بدون أي تعديل في الشكل أو التصميم أو الأنماط).

القالب يحتوي فعليًا على وسمين <script type="application/json">:
  - #embeddedQuestionsData   → مصفوفة الأسئلة
  - #embeddedExamSettings    → إعدادات الامتحان (نوعه ومدته)
نقوم فقط باستبدال محتوى هذين الوسمين نصيًا (نفس الطريقة التي يستخدمها
زر "تحميل نسخة مدمجة" داخل الملف الأصلي نفسه)، فيبقى كل الكود والتصميم كما هو.
"""
import json
import re
import logging

import config

logger = logging.getLogger(__name__)


def _load_template() -> str:
    with open(config.TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _safe_json_for_script_tag(data) -> str:
    """يحوّل بيانات بايثون إلى JSON، مع تأمينها من كسر وسم </script> داخل الصفحة."""
    raw = json.dumps(data, ensure_ascii=False)
    # نفس المعالجة المستخدمة في الملف الأصلي لتفادي كسر وسم HTML
    raw = raw.replace("</", "<\\/")
    return raw


def build_quiz_html(questions: list, exam_title: str = None,
                     exam_type: str = "open", duration_minutes: int = 10,
                     auto_start: bool = True) -> str:
    """
    يبني ملف HTML كامل جاهز للإرسال، بنفس تصميم القالب الأصلي.

    questions: قائمة القواميس الناتجة من quiz_generator.generate_quiz_questions
    exam_type: "open" (بدون وقت) أو "timed" (بوقت محدد)
    """
    template = _load_template()

    questions_json = _safe_json_for_script_tag(questions)
    settings = {
        "examType": exam_type if exam_type in ("open", "timed") else "open",
        "duration": max(1, min(180, int(duration_minutes))),
        "autoStart": bool(auto_start),
    }
    settings_json = _safe_json_for_script_tag(settings)

    # استبدال محتوى وسم الأسئلة المضمّنة
    template, n_questions = re.subn(
        r'(<script type="application/json" id="embeddedQuestionsData">)(.*?)(</script>)',
        lambda m: m.group(1) + questions_json + m.group(3),
        template,
        count=1,
        flags=re.DOTALL,
    )
    if n_questions != 1:
        # لو مالقيناش الوسم بالظبط (مثلاً القالب اتغيّر شكله)، لازم نوقف
        # فورًا بدل ما نرجّع القالب زي ما هو ببياناته التجريبية الأصلية —
        # فشل صامت هنا معناه إرسال كويز غلط تمامًا للمستخدم من غير تحذير.
        raise ValueError(
            "تعذّر إيجاد وسم embeddedQuestionsData داخل القالب. "
            "تأكد إن ملف quiz_template.html لم يتغيّر شكله."
        )

    # استبدال محتوى وسم إعدادات الامتحان
    template, n_settings = re.subn(
        r'(<script type="application/json" id="embeddedExamSettings">)(.*?)(</script>)',
        lambda m: m.group(1) + settings_json + m.group(3),
        template,
        count=1,
        flags=re.DOTALL,
    )
    if n_settings != 1:
        raise ValueError(
            "تعذّر إيجاد وسم embeddedExamSettings داخل القالب. "
            "تأكد إن ملف quiz_template.html لم يتغيّر شكله."
        )

    # تعديل اختياري لعنوان الصفحة إن أردنا تخصيصه بموضوع الكويز
    if exam_title:
        safe_title = exam_title.replace("<", "").replace(">", "").strip()[:80]
        template = re.sub(
            r"<title>.*?</title>",
            f"<title>{safe_title} — Thanawiyah_Quiz🎯</title>",
            template,
            count=1,
            flags=re.DOTALL,
        )

    return template


def save_quiz_html(questions: list, output_path: str, **kwargs) -> str:
    """يبني الكويز ويحفظه في ملف، ويرجع المسار."""
    html = build_quiz_html(questions, **kwargs)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path
