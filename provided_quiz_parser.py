# -*- coding: utf-8 -*-
"""Local, deterministic parser for structured and semi-structured quiz text."""
from __future__ import annotations
import re

QUESTION_RE=re.compile(r'^\s*(?:#{1,6}\s*)?(?:(?:ال)?س(?:ؤال)?\s*)?(\d+)[\s.\-:：)\]]+(.+?)\s*$',re.I)
QUESTION_WORD_RE=re.compile(r'^\s*(?:#{1,6}\s*)?(?:(?:ال)?س(?:ؤال)?|question|q)\s*(?:رقم\s*)?(\d+)?\s*[:：.\-)]\s*(.+?)\s*$',re.I)
OPTION_RE=re.compile(r'^\s*(?:[-*+]\s+|(?:[أا][)\].:\-]|[بب][)\].:\-]|[جج][)\].:\-]|[دد][)\].:\-]|[A-Da-d][)\].:\-]|[1-4][)\].:\-])\s*)(.+?)\s*$')
ANSWER_RE=re.compile(r'^\s*(?:الإجابة\s*(?:الصحيحة)?|الاجابة\s*(?:الصحيحة)?|correct\s*answer|answer)\s*(?:هي|is)?\s*(?:[:：\-]|\s)\s*(?:الخيار\s*|option\s*)?(.+?)\s*$',re.I)
EXPLAIN_RE=re.compile(r'^\s*(?:التفسير|شرح\s*(?:الإجابة|الاجابة)|الشرح|explanation|explain)\s*[:：\-]\s*(.+?)\s*$',re.I)
LETTERS={'أ':0,'ا':0,'إ':0,'آ':0,'ب':1,'ج':2,'د':3,'A':0,'B':1,'C':2,'D':3,'a':0,'b':1,'c':2,'d':3}

def _clean(line): return re.sub(r'[`*_~]','',line).strip()
def _question(line):
    line=_clean(line)
    for rx in (QUESTION_RE,QUESTION_WORD_RE):
        m=rx.match(line)
        if m: return m.group(2).strip()
    # سؤال غير مرقم: عنوان Markdown أو سطر ينتهي بعلامة استفهام.
    plain=re.sub(r'^#{1,6}\s*','',line).strip()
    if plain and plain.endswith(('؟','?')) and not re.match(r'^(?:الإجابة|الاجابة|التفسير|الشرح|answer|explanation)\b',plain,re.I):
        return plain
    return None

def _option(line):
    line=_clean(line); m=OPTION_RE.match(line)
    return m.group(1).strip() if m else None

def _answer_index(value,options):
    value=_clean(value).strip(); low=value.lower()
    for phrase,index in [('الأول',0),('الاول',0),('first',0),('الثاني',1),('الثانى',1),('second',1),('الثالث',2),('third',2),('الرابع',3),('fourth',3)]:
        if phrase in low:return index
    m=re.search(r'[أاإآبجدABCDabcd]',value)
    if m and m.group(0) in LETTERS:return LETTERS[m.group(0)]
    m=re.search(r'\b([1-4])\b',value)
    if m:return int(m.group(1))-1
    for i,opt in enumerate(options):
        if value==opt or value in opt:return i
    return None

def parse_provided_quiz(text:str)->list[dict]:
    rows=[]; current=None; mode=None
    for raw in (text or '').replace('\r','').split('\n'):
        line=raw.strip()
        if not line or re.fullmatch(r'[-=*_# ]{3,}',line):continue
        # إزالة علامات Markdown حول العناوين والخيارات دون المساس بمحتوى السؤال.
        line=re.sub(r'^\s*>\s*','',line)
        qtext=_question(line)
        if qtext:
            # لا نعتبر علامة الاستفهام داخل سطر خيار سؤالًا جديدًا.
            if current is None or len(current.get('options',[])) >= 4 or not current.get('options'):
                if current:rows.append(current)
                current={'question':qtext,'options':[],'answer_raw':'','explanation':''};mode=None;continue
        if current is None:continue
        opt=_option(line)
        if opt is not None:
            current['options'].append(opt);mode='options';continue
        am=ANSWER_RE.match(_clean(line))
        if am:current['answer_raw']=am.group(1).strip();mode='answer';continue
        em=EXPLAIN_RE.match(_clean(line))
        if em:current['explanation']=em.group(1).strip();mode='explanation';continue
        if mode=='answer':current['answer_raw']+=' '+_clean(line)
        elif mode=='explanation':current['explanation']+=' '+_clean(line)
        elif mode=='options' and current['options']:current['options'][-1]+=' '+_clean(line)
    if current:rows.append(current)
    if not rows:raise ValueError('لم يتم العثور على أسئلة. أرسل كل سؤال في سطر مستقل، ويفضل أن ينتهي بعلامة ؟ أو ?.')
    result=[]
    for n,row in enumerate(rows,1):
        if len(row['options'])!=4:raise ValueError(f'السؤال {n} يجب أن يحتوي على 4 خيارات، وتم العثور على {len(row["options"])}.')
        correct=_answer_index(row['answer_raw'],row['options'])
        if correct is None:raise ValueError(f'تعذر تحديد الإجابة الصحيحة للسؤال {n}. اكتب: الإجابة: أ أو الإجابة: 1')
        result.append({'question':row['question'],'options':row['options'],'correct':correct,'explanation':row['explanation'] or f'الإجابة الصحيحة هي: {row["options"][correct]}.','why_wrong':['هذا الخيار غير صحيح.' if i!=correct else 'هذا هو الخيار الصحيح.' for i in range(4)],'bloom':'understand','difficulty':'medium','topic':'عام','imageUrl':'','needs_image':False})
    return result

def looks_like_provided_quiz(text:str)->bool:
    return bool(re.search(r'(?im)^\s*(?:#{1,6}\s*)?(?:(?:(?:ال)?س(?:ؤال)?|question|q)\s*)?\d+[\s.\-:：)\]]+',text or '')) or bool(re.search(r'(?im)^\s*(?:(?:ال)?س(?:ؤال)?|question|q)\s*\d*\s*[:：]',text or '')) or bool(re.search(r'(?m)^\s*(?:#{1,6}\s*)?[^\n]{4,}[؟?]\s*$',text or ''))
