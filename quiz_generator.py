# -*- coding: utf-8 -*-
"""
توليد أسئلة اختيار من متعدد من نص تعليمي، بنفس الصيغة (schema)
التي يتوقعها قالب Thanawiyah_Quiz HTML:

{
  "question": "...",
  "options": ["...", "...", "...", "..."],
  "correct": 0-3,
  "explanation": "...",
  "why_wrong": ["...", "...", "...", "..."],   # تفسير كل خيار خاطئ على حدة
  "bloom": "remember|understand|apply|analyze|evaluate|create",
  "difficulty": "easy|medium|hard",
  "topic": "...",
  "imageUrl": ""
}
"""
import json
import re
import random
import logging

from ai_router import get_router
import config
import image_generator

logger = logging.getLogger(__name__)

BLOOM_LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]

SYSTEM_INSTRUCTIONS_AR = """أنت خبير تربوي متخصص في بناء اختبارات اختيار من متعدد عالية الجودة
لطلاب المرحلة الثانوية، باللغتين العربية والإنجليزية.

مهمتك: قراءة المحتوى التعليمي المُعطى، فهم أفكاره الأساسية بعمق، ثم توليد أسئلة
اختيار من متعدد (4 خيارات لكل سؤال) تعتمد بشكل أساسي على:
- الفهم العميق للمفهوم (Understand)
- التطبيق على أمثلة جديدة لم تُذكر حرفيًا في النص (Apply)
- التحليل والمقارنة بين الحالات (Analyze)
- الاستنتاج المنطقي من المعطيات (Evaluate / Analyze)

تجنب الأسئلة السطحية التي تعتمد على الحفظ الحرفي فقط، إلا في نسبة قليلة جدًا
لتثبيت أساسيات المصطلحات إن لزم الأمر.

إذا كان المحتوى عن قواعد نحوية أو لغوية (عربي أو إنجليزي)، اصنع أسئلة تطبيقية
على جمل وأمثلة جديدة تختبر فهم القاعدة وليس استظهارها فقط.

يجب أن يكون لكل سؤال:
1. "question": نص السؤال بوضوح تام.
2. "options": قائمة من 4 خيارات نصية فقط، متقاربة المستوى بحيث لا يكون الصحيح واضحًا بالشكل.
3. "correct": رقم صحيح (0 أو 1 أو 2 أو 3) يمثل انديكس الخيار الصحيح.
4. "explanation": شرح مبسّط وواضح لماذا هذه الإجابة صحيحة تحديدًا، بأسلوب سهل يناسب طالب المرحلة الثانوية.
5. "why_wrong": قائمة من 4 عناصر نصية، كل عنصر يشرح بإيجاز ولطف لماذا هذا الخيار
   بالتحديد (بنفس ترتيب options) غير صحيح. للخيار الصحيح، اكتب جملة قصيرة تؤكد صحته
   (مثل: "هذا هو الخيار الصحيح كما وضحنا في التفسير.").
6. "bloom": واحد فقط من: remember, understand, apply, analyze, evaluate, create
   (حسب المهارة الذهنية الفعلية التي يتطلبها السؤال).
7. "difficulty": واحد من: easy, medium, hard.
8. "topic": اسم قصير للموضوع الفرعي الذي يتناوله السؤال.
9. "imageUrl": اترك القيمة دائمًا سلسلة فارغة "".
10. "needs_image": true أو false فقط — true إذا كان السؤال سيستفيد فعليًا
    من رسم توضيحي بسيط (مخطط، شكل هندسي، رسم بياني، خط زمني، دورة...) لفهم
    السؤال بصريًا، و false لو السؤال نصي بحت ولا يحتاج رسمًا. اجعل هذا
    true لنسبة قليلة فقط من الأسئلة (الأسئلة التي تستفيد بصريًا فعلًا مثل
    الهندسة أو الفيزياء أو الأحياء أو مخططات نحوية)، ولباقي الأسئلة اجعلها
    false.

مهم جدًا بخصوص اللغة:
- إذا كان المحتوى المصدر بالعربية، اكتب كل الأسئلة والخيارات والتفسيرات بالعربية الفصحى السليمة نحويًا.
- إذا كان المحتوى بالإنجليزية، اكتب كل شيء بإنجليزية سليمة قواعديًا.
- حافظ على المصطلحات العلمية/التقنية كما هي إذا كانت شائعة بلغة واحدة.

أعد الناتج **فقط** كمصفوفة JSON صالحة (بدون أي نص إضافي قبلها أو بعدها،
بدون علامات ```json، بدون أي تعليق) بالضبط بهذا الشكل:

[
  {
    "question": "...",
    "options": ["...", "...", "...", "..."],
    "correct": 0,
    "explanation": "...",
    "why_wrong": ["...", "...", "...", "..."],
    "bloom": "understand",
    "difficulty": "medium",
    "topic": "...",
    "imageUrl": "",
    "needs_image": false
  }
]
"""


def _build_prompt(content_text: str, num_questions: int, extra_instructions: str = "") -> str:
    # نحد طول النص المُرسل تفاديًا لتضخم التوكنز بشكل مبالغ فيه
    max_chars = 18000
    trimmed = content_text.strip()
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars] + "\n...[تم اختصار النص لطوله]"

    extra = f"\nملاحظات إضافية من المستخدم: {extra_instructions}\n" if extra_instructions else ""

    return f"""{SYSTEM_INSTRUCTIONS_AR}

المحتوى التعليمي المصدر:
\"\"\"
{trimmed}
\"\"\"

المطلوب: أنشئ بالضبط {num_questions} سؤالًا حسب المواصفات أعلاه.
{extra}
تذكير أخير: الناتج يجب أن يكون مصفوفة JSON صالحة فقط، بدون أي نص أو تعليق خارجها.
"""


def _clean_json_response(raw_text: str) -> str:
    """يزيل أي أسوار markdown أو نص زائد حول الـ JSON."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    # لو فيه نص قبل أو بعد المصفوفة، نحاول نلقط أول [ وآخر ]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return text


def _validate_and_fix_question(item: dict, idx: int) -> dict:
    """يتحقق من صحة بنية السؤال ويصلح ما يمكن إصلاحه، أو يرفع خطأ إن كان غير قابل للإصلاح."""
    if not isinstance(item.get("question"), str) or not item["question"].strip():
        raise ValueError(f"السؤال رقم {idx + 1}: نص السؤال مفقود.")

    options = item.get("options")
    if not isinstance(options, list) or len(options) != 4:
        raise ValueError(f"السؤال رقم {idx + 1}: يجب أن يحتوي على 4 خيارات بالضبط.")
    options = [str(o).strip() for o in options]
    if any(not o for o in options):
        raise ValueError(f"السؤال رقم {idx + 1}: أحد الخيارات فارغ.")

    correct = item.get("correct")
    if not isinstance(correct, int):
        try:
            correct = int(correct)
        except (TypeError, ValueError):
            raise ValueError(f"السؤال رقم {idx + 1}: قيمة correct غير صالحة.")
    if correct < 0 or correct > 3:
        raise ValueError(f"السؤال رقم {idx + 1}: correct يجب أن يكون بين 0 و3.")

    explanation = item.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        explanation = f"الإجابة الصحيحة هي: {options[correct]}."

    why_wrong = item.get("why_wrong")
    if not isinstance(why_wrong, list) or len(why_wrong) != 4:
        why_wrong = ["هذا الخيار لا يحقق الشرط المطلوب في السؤال." for _ in range(4)]
    why_wrong = [str(w).strip() or "هذا الخيار غير صحيح." for w in why_wrong]

    bloom = str(item.get("bloom", "understand")).lower().strip()
    if bloom not in BLOOM_LEVELS:
        bloom = "understand"

    difficulty = str(item.get("difficulty", "medium")).lower().strip()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"

    topic = item.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        topic = "عام"

    needs_image = bool(item.get("needs_image", False))

    return {
        "question": item["question"].strip(),
        "options": options,
        "correct": correct,
        "explanation": explanation.strip(),
        "why_wrong": why_wrong,
        "bloom": bloom,
        "difficulty": difficulty,
        "topic": topic.strip(),
        "imageUrl": "",
        "needs_image": needs_image
    }


def _normalize_for_dedupe(text: str) -> str:
    """توحيد شكل نص السؤال لغرض كشف التكرار (يتجاهل المسافات الزائدة والتشكيل البسيط)."""
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    return text


def _dedupe_questions(questions: list) -> list:
    """يشيل الأسئلة المكررة (نفس نص السؤال تقريبًا) محتفظًا بأول ظهور فقط."""
    seen = set()
    unique = []
    for q in questions:
        key = _normalize_for_dedupe(q["question"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return unique


def _shuffle_options(question: dict, rng: random.Random) -> dict:
    """
    يخلط ترتيب الخيارات (options) عشوائيًا، ويحدّث index الإجابة الصحيحة
    (correct) وترتيب تفسيرات الخطأ (why_wrong) بنفس الترتيب الجديد — عشان
    نتجنب اعتماد النموذج على وضع الإجابة الصحيحة دايمًا في نفس المكان.
    """
    n = len(question["options"])
    order = list(range(n))
    rng.shuffle(order)

    new_options = [question["options"][i] for i in order]
    new_why_wrong = [question["why_wrong"][i] for i in order]
    new_correct = order.index(question["correct"])

    question["options"] = new_options
    question["why_wrong"] = new_why_wrong
    question["correct"] = new_correct
    return question


def _tokens_for_question_count(num_questions: int) -> int:
    """
    عدد التوكنز المسموح للاستجابة يتناسب مع عدد الأسئلة المطلوب، عشان
    الأسئلة الكتير (زي 30 أو 40 سؤال) متتقطعش في نص الـ JSON وتفشل في
    الـ parsing. نحسب تقريبيًا ~350 توكن لكل سؤال (نص + 4 خيارات + شرح +
    4 أسباب خطأ) + هامش أمان.
    """
    estimated = 350 * num_questions + 1000
    return max(8192, min(32768, estimated))


def _generate_batch(content_text: str, num_questions: int,
                     extra_instructions: str = "") -> tuple:
    """
    يعمل استدعاء واحد لـ Gemini، ويرجع (validated_questions, error_message).
    error_message يبقى None لو نجح (حتى لو عدد الأسئلة الصالحة أقل من المطلوب).
    """
    prompt = _build_prompt(content_text, num_questions, extra_instructions)

    try:
        client = get_router()
        raw_response = client.generate(
            prompt,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": _tokens_for_question_count(num_questions),
            }
        )
    except Exception as e:
        logger.exception("فشل استدعاء Gemini لتوليد الأسئلة")
        return [], f"فشل الاتصال بنموذج الذكاء الاصطناعي: {e}"

    cleaned = _clean_json_response(raw_response)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"فشل تحليل JSON من Gemini: {e}\nالنص: {cleaned[:500]}")
        return [], "تعذّر فهم استجابة الذكاء الاصطناعي (تنسيق JSON غير صالح)."

    if not isinstance(parsed, list) or not parsed:
        return [], "لم يُنشئ النموذج أي أسئلة صالحة."

    validated = []
    for idx, item in enumerate(parsed):
        try:
            validated.append(_validate_and_fix_question(item, idx))
        except ValueError as e:
            logger.warning(f"تخطي سؤال غير صالح: {e}")
            continue

    return validated, None


def _generate_in_batches(content_text: str, num_questions: int,
                          extra_instructions: str = "") -> tuple:
    """
    يقسّم توليد الأسئلة إلى دفعات (batches) بدل استدعاء واحد ضخم لـ Gemini،
    وذلك فقط عندما يتجاوز العدد المطلوب config.BATCH_THRESHOLD. هذا يقلل
    احتمال تقطّع/فشل الـ JSON الناتج في الكويزات الكبيرة (30-40 سؤال)،
    ويزيد تنوع الأسئلة لأن كل دفعة تُطلب بشكل منفصل.

    للكويزات الصغيرة (<= BATCH_THRESHOLD) يبقى السلوك تمامًا كاستدعاء واحد
    كما كان، بدون أي تغيير.

    يرجع (validated_questions, error_message) — error_message تبقى None
    لو نجحت أي دفعة على الأقل، حتى لو فشلت دفعات أخرى.
    """
    if num_questions <= config.BATCH_THRESHOLD:
        return _generate_batch(content_text, num_questions, extra_instructions)

    batch_size = max(1, config.QUESTIONS_PER_BATCH)
    remaining = num_questions
    all_validated = []
    first_error = None
    batch_num = 0

    while remaining > 0:
        batch_num += 1
        this_batch_count = min(batch_size, remaining)

        batch_extra = extra_instructions
        if batch_num > 1:
            diversity_note = (
                "ملحوظة: هذه دفعة إضافية من نفس الكويز، ولّد أسئلة جديدة "
                "ومختلفة تمامًا عن أي أسئلة قد تكون وُلّدت في دفعات سابقة، "
                "وحاول تغطية جوانب أخرى من المحتوى لزيادة التنوع."
            )
            batch_extra = f"{extra_instructions}\n{diversity_note}" if extra_instructions else diversity_note

        validated, error = _generate_batch(content_text, this_batch_count, batch_extra)
        if validated:
            all_validated.extend(validated)
        elif first_error is None:
            first_error = error

        remaining -= this_batch_count

    return all_validated, (None if all_validated else first_error)


def generate_quiz_questions(content_text: str, num_questions: int = None,
                             extra_instructions: str = "") -> dict:
    """
    يولّد أسئلة الكويز من نص المحتوى.
    يرجع: {"success": bool, "questions": list, "error": str|None}

    لو أول محاولة رجّعت أسئلة صالحة أقل من المطلوب (بسبب رفض بعضها في
    التحقق)، بيحاول مرة إضافية يكمّل الفرق بدل ما يبعت للمستخدم عدد
    أقل من غير ما يحاول.
    """
    num_questions = num_questions or config.DEFAULT_QUESTIONS
    num_questions = max(config.MIN_QUESTIONS, min(config.MAX_QUESTIONS, num_questions))

    if not content_text or len(content_text.strip()) < 30:
        return {"success": False, "questions": [],
                "error": "المحتوى المستخرج قصير جدًا أو فارغ، لا يكفي لبناء كويز مفيد."}

    validated, error = _generate_in_batches(content_text, num_questions, extra_instructions)
    if error and not validated:
        return {"success": False, "questions": [], "error": error}

    validated = _dedupe_questions(validated)

    # محاولة إضافية واحدة لتعويض النقص لو العدد الصالح أقل من المطلوب
    max_extra_attempts = 1
    attempt = 0
    while len(validated) < num_questions and attempt < max_extra_attempts:
        attempt += 1
        missing = num_questions - len(validated)
        logger.info(f"عدد الأسئلة الصالحة ({len(validated)}) أقل من المطلوب ({num_questions})، "
                    f"محاولة توليد {missing} سؤال إضافي.")
        extra_batch, _ = _generate_in_batches(
            content_text, missing,
            extra_instructions=(extra_instructions +
                                 "\nملحوظة: ولّد أسئلة جديدة ومختلفة عن أي أسئلة سابقة.")
        )
        validated = _dedupe_questions(validated + extra_batch)

    if not validated:
        return {"success": False, "questions": [],
                "error": error or "كل الأسئلة الناتجة كانت غير صالحة البنية. حاول مرة أخرى."}

    # نقص العدد لحد المطلوب بالظبط (لو زاد بسبب محاولة التعويض)
    validated = validated[:num_questions]

    rng = random.Random()
    validated = [_shuffle_options(q, rng) for q in validated]

    # توليد الصور التوضيحية (اختياري) — يحدث بعد اكتمال وتصحيح الأسئلة
    # نفسها تمامًا، وبمعزل تام عنها، عشان فشل توليد صورة واحدة لا يؤثر
    # إطلاقًا على نص الأسئلة أو يفشل الكويز كله.
    try:
        validated = image_generator.attach_images_to_questions(validated)
    except Exception:
        logger.exception("خطأ غير متوقع أثناء توليد الصور التوضيحية — تم تجاهله والمتابعة بدون صور.")

    return {"success": True, "questions": validated, "error": None}
