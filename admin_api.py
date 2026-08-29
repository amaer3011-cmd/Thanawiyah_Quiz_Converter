from __future__ import annotations
import os, sqlite3
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from store import store

app=FastAPI(title='Thanawiyah Quiz Admin')
TOKEN=os.getenv('ADMIN_PANEL_TOKEN','change-me')
def guard(token:str|None):
    if not token or token != TOKEN: raise HTTPException(status_code=401, detail='Unauthorized')
@app.get('/', response_class=HTMLResponse)
def dashboard(x_admin_token:str|None=Header(default=None)):
    guard(x_admin_token); s=store.stats()
    return f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>Thanawiyah_Quiz🎯 Admin</title><style>body{{font-family:Arial;background:#eff6ff;padding:32px;color:#0f172a}}.grid{{display:flex;gap:16px;flex-wrap:wrap}}.card{{background:white;border-radius:18px;padding:22px;min-width:180px;box-shadow:0 8px 24px #0f172a18}}b{{font-size:32px;color:#2563eb}}</style><h1>Thanawiyah_Quiz🎯</h1><p>لوحة تحكم الأدمن</p><div class="grid">{''.join(f'<div class="card"><div>{k}</div><b>{v}</b></div>' for k,v in s.items())}</div></html>'''
@app.get('/api/stats')
def stats(x_admin_token:str|None=Header(default=None)):
    guard(x_admin_token); return store.stats()
@app.get('/api/quizzes')
def quizzes(x_admin_token:str|None=Header(default=None)):
    guard(x_admin_token)
    with store._connect() as c: return [dict(r) for r in c.execute('SELECT id,telegram_id,title,created_at FROM quizzes ORDER BY id DESC LIMIT 200')]
@app.get('/api/results')
def results(x_admin_token:str|None=Header(default=None)):
    guard(x_admin_token)
    with store._connect() as c: return [dict(r) for r in c.execute('SELECT * FROM results ORDER BY id DESC LIMIT 200')]
