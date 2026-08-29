# -*- coding: utf-8 -*-
"""Parser for user-authored questions; no AI generation is used."""
from __future__ import annotations
import re

QUESTION_RE = re.compile(r'^\s*(?:س(?:ؤال)?\s*)?(\d+)[\s.\-:：)\]]+(.+?)\s*$', re.I)
OPTION_RE = re.compile(r'^\s*(?:[أا][)\].:\-]|[بب][)\].:\-]|[جج][)\].:\-]|[دد][)\].:\-]|[A-Da-d][)\].:\-]|\d+[)\].:\-])\s*(.+?)\s*$')
ANSWER_RE = re.compile(r'^\s*(?:الإجابة الصحيحة|الإجابة|الاجابة|correct answer|answer)\s*[:：\-]\s*(.+?)\s*$', re.I)
EXPLAIN_RE = re.compile(r'^\s*(?:التفسير|شرح الإجابة|الشرح|explanation|explain)\s*[:：\-]\s*(.+?)\s*$', re.I)
LETTERS = {'أ':0,'ا':0,'إ':0,'آ':0,'ب':1,'ج':2,'د':3,'A':0,'B':1,'C':2,'D':3,'a':0,'b':1,'c':2,'d':3}

def _answer_index(value, options):
    value=value.strip()
    m=re.search(r'([أاإآبجدABCDabcd])', value)
    if m and m.group(1) in LETTERS: return LETTERS[m.group(1)]
    try:
        n=int(re.search(r'\d+',value).group())
        if 0 <= n <= 3: return n
        if 1 <= n <= 4: return n-1
    except Exception: pass
    for i,opt in enumerate(options):
        if value == opt.strip() or value in opt: return i
    return None

def parse_provided_quiz(text: str) -> list[dict]:
    rows=[]; current=None; mode=None
    for raw in text.splitlines():
        line=raw.strip()
        if not line: continue
        qm=QUESTION_RE.match(line)
        if qm:
            if current: rows.append(current)
            current={'question':qm.group(2).strip(),'options':[],'answer_raw':'','explanation':'','topic':'عام'}; mode=None; continue
        if current is None: continue
        om=OPTION_RE.match(line)
        if om:
            current['options'].append(om.group(1).strip()); mode='options'; continue
        am=ANSWER_RE.match(line)
        if am: current['answer_raw']=am.group(1).strip(); mode='answer'; continue
        em=EXPLAIN_RE.match(line)
        if em: current['explanation']=em.group(1).strip(); mode='explanation'; continue
        if mode=='answer': current['answer_raw'] += ' '+line
        elif mode=='explanation': current['explanation'] += ' '+line
        elif mode=='options' and len(current['options']) < 4: current['options'][-1] += ' '+line
    if current: rows.append(current)
    result=[]
    for n,row in enumerate(rows,1):
        if len(row['options']) != 4: raise ValueError(f'السؤال {n} يجب أن يحتوي على 4 خيارات، وتم العثور على {len(row["options"])}.')
        correct=_answer_index(row['answer_raw'],row['options'])
        if correct is None: raise ValueError(f'تعذر تحديد الإجابة الصحيحة للسؤال {n}: {row["answer_raw"]}')
        result.append({'question':row['question'],'options':row['options'],'correct':correct,'explanation':row['explanation'] or f'الإجابة الصحيحة هي: {row["options"][correct]}.','why_wrong':['هذا الخيار غير صحيح.' if i != correct else 'هذا هو الخيار الصحيح.' for i in range(4)],'bloom':'understand','difficulty':'medium','topic':row['topic'],'imageUrl':'','needs_image':False})
    if not result: raise ValueError('لم يتم العثور على أسئلة. استخدم صيغة السؤال والخيارات والإجابة الموضحة في المثال.')
    return result

def looks_like_provided_quiz(text: str) -> bool:
    return bool(re.search(r'(?im)^\s*(?:س(?:ؤال)?\s*)?\d+[\s.\-:：)\]]+',text or '')) and bool(re.search(r'(?im)^\s*(?:الإجابة الصحيحة|الإجابة|الاجابة|correct answer|answer)\s*[:：\-]',text or ''))
