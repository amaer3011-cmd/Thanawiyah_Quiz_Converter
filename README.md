# Thanawiyah_Quiz_Converter

بوت Telegram مستقل يحوّل نص الأسئلة الجاهزة، مع الخيارات والإجابة الصحيحة والتفسير، إلى ملف HTML تفاعلي بنفس تصميم **Thanawiyah_Quiz🎯**.

لا يستخدم هذا البوت Gemini أو OpenRouter أو YouTube؛ لذلك لا يحتاج إلا إلى توكن Telegram. يَحفظ الأسئلة التي ترسلها كما هي، ويضمّنها داخل القالب الأزرق، ثم يبدأ الاختبار مباشرة عند فتح الملف.

## التشغيل المحلي

```bash
cp .env.example .env
# ضع TELEGRAM_BOT_TOKEN الحقيقي داخل .env
pip install -r requirements.txt
python bot.py
```

## التشغيل عبر Docker

```bash
docker build -t thanawiyah-quiz-converter .
docker run --env-file .env --restart unless-stopped thanawiyah-quiz-converter
```

## الصيغة المدعومة

```text
1) ما عاصمة مصر؟
أ) القاهرة
ب) الرباط
ج) دمشق
د) تونس
الإجابة: أ
التفسير: القاهرة هي عاصمة جمهورية مصر العربية.
```

يمكن إرسال النص مباشرة إلى البوت أو رفعه كملف `.txt` أو `.md`. يجب أن يحتوي كل سؤال على أربعة خيارات وإجابة صحيحة، بينما التفسير اختياري. يدعم parser صيغ `1)` و`س1:` والخيارات العربية أو الإنجليزية.

راجع [QUESTION_FORMAT.md](QUESTION_FORMAT.md) لأمثلة إضافية.
