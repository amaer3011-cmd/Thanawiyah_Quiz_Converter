# -*- coding: utf-8 -*-
"""Gemini-first AI router with OpenRouter fallback and key rotation."""
from __future__ import annotations
import json, os, random, time
import requests
import config
from gemini_client import get_client

class AIRouter:
    def __init__(self):
        self.keys=list(config.OPENROUTER_API_KEYS)
        self.models=list(config.OPENROUTER_MODELS)
        self.timeout=config.AI_REQUEST_TIMEOUT
        self.retries=config.AI_RETRIES
    def generate(self,prompt:str,generation_config:dict|None=None)->str:
        errors=[]
        try:
            return get_client().generate_text(prompt,generation_config=generation_config or {})
        except Exception as exc:
            errors.append(f'Gemini: {exc}')
        keys=self.keys[:]; random.shuffle(keys)
        for key in keys:
            for model in self.models:
                for attempt in range(self.retries):
                    try:
                        payload={'model':model,'messages':[{'role':'user','content':prompt}], 'temperature':0.7, 'response_format':{'type':'json_object'}}
                        response=requests.post('https://openrouter.ai/api/v1/chat/completions',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json','X-Title':'Thanawiyah_Quiz'},json=payload,timeout=self.timeout)
                        response.raise_for_status()
                        data=response.json()
                        return data['choices'][0]['message']['content']
                    except Exception as exc:
                        status_code = getattr(locals().get('response'), 'status_code', None)
                        if status_code in (401, 403):
                            errors.append(f'OpenRouter/{model}: Unauthorized (تحقق من OPENROUTER_API_KEY/OPENROUTER_API_KEYS)')
                        else:
                            errors.append(f'OpenRouter/{model}: {exc}')
                        if attempt+1<self.retries: time.sleep(0.5*(2**attempt))
        if not keys:
            raise RuntimeError('لا يوجد مفتاح OpenRouter احتياطي مضبوط. أضف OPENROUTER_API_KEY أو OPENROUTER_API_KEYS في Environment Variables.')
        raise RuntimeError('فشل جميع مزودي الذكاء الاصطناعي: ' + ' | '.join(errors[-4:]))

_router=None
def get_router():
    global _router
    if _router is None: _router=AIRouter()
    return _router
