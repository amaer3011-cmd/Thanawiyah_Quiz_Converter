# -*- coding: utf-8 -*-
"""
عميل Gemini مع دعم عدة مفاتيح API والتبديل التلقائي بينها
عند تجاوز الحصة (quota) أو حدوث خطأ مؤقت في أحد المفاتيح.

ملاحظة تصميم مهمة: مكتبة google-generativeai تستخدم genai.configure(api_key=...)
كإعداد عالمي (global) على مستوى العملية كلها، مش مربوط بكائن معيّن. لو استُخدم
هذا العميل من كذا مستخدم/طلب في نفس الوقت (حتى مع asyncio.to_thread)، ممكن
يحصل تعارض (race condition): مستخدم يبدأ الطلب بمفتاح، ولحظة التنفيذ يبقى
المفتاح اتغيّر بسبب طلب مستخدم تاني. لتفادي ده، كل استدعاء فعلي لـ Gemini
(تهيئة المفتاح + توليد المحتوى) بيتم داخل قفل (threading.Lock) واحد، يعني
الطلبات بتتنفذ بالتتابع (serialized) بدل التوازي الكامل. الحل الأمثل طويل
المدى هو الانتقال لمكتبة google-genai الأحدث اللي بتدّي genai.Client(api_key=...)
مستقل لكل طلب بدون حالة عالمية، لكن ده تغيير أكبر (تغيير SDK بالكامل).
"""
import logging
import itertools
import threading
import google.generativeai as genai

import config

logger = logging.getLogger(__name__)

# قفل عالمي واحد يضمن إن تهيئة المفتاح (genai.configure) واستدعاء التوليد
# يحصلوا معًا كوحدة واحدة (atomic) من غير ما طلب تاني يقاطعهم في النص.
_gemini_call_lock = threading.Lock()


class GeminiKeyPoolError(Exception):
    """تُرفع عندما تفشل كل المفاتيح المتاحة."""
    pass


class GeminiContentBlockedError(Exception):
    """تُرفع عند فشل غير متعلق بالحصة (quota) — زي حظر محتوى أو خطأ في الطلب نفسه —
    حيث تبديل المفتاح لن يحل المشكلة."""
    pass


class GeminiClient:
    def __init__(self):
        if not config.GEMINI_API_KEYS:
            raise ValueError(
                "لا يوجد أي مفتاح Gemini في متغير البيئة GEMINI_API_KEYS. "
                "أضف مفتاحًا واحدًا على الأقل في ملف .env"
            )
        self._keys = list(config.GEMINI_API_KEYS)
        self._key_cycle = itertools.cycle(range(len(self._keys)))
        self._current_idx = 0
        self._configure(self._keys[0])

    def _configure(self, key: str):
        genai.configure(api_key=key)

    def _next_key(self):
        self._current_idx = (self._current_idx + 1) % len(self._keys)
        return self._keys[self._current_idx]

    def _is_quota_or_transient_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        signals = [
            "quota", "rate limit", "resource_exhausted", "429",
            "unavailable", "503", "internal", "500", "deadline",
        ]
        return any(s in msg for s in signals)

    def _run_with_key_pool(self, build_content, model_name: str,
                            generation_config: dict, media_label: str = "") -> str:
        """
        منطق مشترك: يهيّئ المفتاح ويستدعي Gemini جوه قفل واحد (لمنع تعارض
        المفاتيح بين الطلبات المتزامنة)، ويبدّل المفاتيح فقط عند أخطاء
        الحصة/الأخطاء المؤقتة الحقيقية. أي خطأ تاني (محتوى محظور، طلب غير
        صالح...) بيوقف فورًا من غير ما يضيّع باقي المفاتيح على مشكلة
        تبديل المفتاح مش هيحلها.
        """
        last_error = None
        attempts = len(self._keys)

        for attempt in range(attempts):
            key = self._keys[self._current_idx]
            try:
                with _gemini_call_lock:
                    self._configure(key)
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(
                        build_content(),
                        generation_config=generation_config or {}
                    )
                if not response or not getattr(response, "text", None):
                    raise ValueError("استجابة فارغة من Gemini (قد يكون المحتوى محظورًا لأسباب أمان)")
                return response.text
            except Exception as e:
                last_error = e
                suffix = f" ({media_label})" if media_label else ""
                logger.warning(
                    f"فشل المفتاح رقم {self._current_idx + 1}/{len(self._keys)}{suffix}: {e}"
                )
                if self._is_quota_or_transient_error(e):
                    if attempt < attempts - 1:
                        self._next_key()
                        continue
                    break
                # خطأ غير مؤقت (زي حظر محتوى أو طلب غير صالح) — تبديل المفتاح
                # مش هيحل المشكلة، فنوقف فورًا بدل ما نضيّع باقي المفاتيح.
                raise GeminiContentBlockedError(
                    f"فشل الطلب لسبب غير متعلق بالحصة (تبديل المفتاح لن يساعد): {e}"
                ) from e

        raise GeminiKeyPoolError(
            f"فشلت كل المفاتيح المتاحة ({attempts}). آخر خطأ: {last_error}"
        )

    def generate_text(self, prompt: str, model_name: str = None,
                       generation_config: dict = None) -> str:
        """يولّد نصًا من برومبت، مع محاولة التبديل بين المفاتيح عند الفشل."""
        model_name = model_name or config.GEMINI_TEXT_MODEL
        return self._run_with_key_pool(lambda: prompt, model_name, generation_config)

    def generate_from_media(self, prompt: str, media_parts: list,
                             model_name: str = None,
                             generation_config: dict = None) -> str:
        """
        يولّد نصًا من برومبت + وسائط (صور مثلاً).
        media_parts: list of dicts بصيغة {"mime_type": "...", "data": bytes}
        """
        model_name = model_name or config.GEMINI_VISION_MODEL
        return self._run_with_key_pool(
            lambda: [prompt] + media_parts, model_name, generation_config, media_label="وسائط"
        )


# نسخة وحيدة (singleton) تُستخدم في كل المشروع
_client_instance = None


def get_client() -> GeminiClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = GeminiClient()
    return _client_instance
