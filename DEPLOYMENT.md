# Thanawiyah_Quiz🎯 — التشغيل والنشر

## التشغيل المحلي

انسخ `.env.example` إلى `.env` وضع `TELEGRAM_BOT_TOKEN` ومفاتيح Gemini. يمكن إضافة عدة مفاتيح في `GEMINI_API_KEYS`، كما يمكن وضع عدة مفاتيح OpenRouter في `OPENROUTER_API_KEYS` مفصولة بفواصل. يبدأ النظام بـ Gemini ثم يجرب النماذج والمفاتيح الاحتياطية تلقائيًا عند الفشل.

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Docker Compose

```bash
docker compose up -d --build
```

يعمل البوت كخدمة مستقلة، بينما تعمل لوحة الأدمن على `http://SERVER_IP:8000`. مرّر قيمة `ADMIN_PANEL_TOKEN` في الطلبات عبر ترويسة `X-Admin-Token`. لا تستخدم القيمة الافتراضية `change-me` في بيئة الإنتاج، ويفضل وضع اللوحة خلف HTTPS وReverse Proxy مع تقييد الوصول إلى عنوان IP الإداري.

## نقاط API الإدارية

| المسار | الوظيفة |
|---|---|
| `/` | لوحة إحصائيات HTML بسيطة |
| `/api/stats` | عدد المستخدمين والكويزات والنتائج |
| `/api/quizzes` | آخر الكويزات المولدة |
| `/api/results` | النتائج التي تم تسجيلها عبر API |

النسخة الحالية تحفظ الكويزات في SQLite داخل volume دائم حتى لا تضيع عند إعادة تشغيل الحاوية. وللنشر واسع النطاق، يجب نقل طبقة `Store` إلى PostgreSQL وإضافة Student WebApp يستقبل تسليمات HTML عبر API موثق ومصادق عليه؛ بنية التخزين الحالية تفصل هذه الطبقة عن منطق البوت لتسهيل الترحيل.
