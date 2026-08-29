from __future__ import annotations
import json, os, sqlite3, threading, time
from pathlib import Path

class Store:
    def __init__(self, path: str|None=None):
        self.path=path or os.getenv('DATABASE_PATH', str(Path(__file__).with_name('quizbot.db')))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock=threading.Lock(); self._init()
    def _connect(self):
        con=sqlite3.connect(self.path, check_same_thread=False); con.row_factory=sqlite3.Row; return con
    def _init(self):
        with self._connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS users(telegram_id INTEGER PRIMARY KEY, username TEXT, first_seen INTEGER, last_seen INTEGER);
            CREATE TABLE IF NOT EXISTS quizzes(id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, title TEXT, questions_json TEXT, created_at INTEGER);
            CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY AUTOINCREMENT, quiz_id INTEGER, telegram_id INTEGER, score INTEGER, total INTEGER, answers_json TEXT, created_at INTEGER);''')
    def upsert_user(self, telegram_id:int, username:str=''):
        now=int(time.time())
        with self.lock, self._connect() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,last_seen=excluded.last_seen',(telegram_id,username,now,now))
    def save_quiz(self, telegram_id:int, title:str, questions:list[dict])->int:
        with self.lock, self._connect() as c:
            cur=c.execute('INSERT INTO quizzes(telegram_id,title,questions_json,created_at) VALUES(?,?,?,?)',(telegram_id,title,json.dumps(questions,ensure_ascii=False),int(time.time())))
            return int(cur.lastrowid)
    def save_result(self, quiz_id:int, telegram_id:int, score:int, total:int, answers:list):
        with self.lock, self._connect() as c:
            c.execute('INSERT INTO results(quiz_id,telegram_id,score,total,answers_json,created_at) VALUES(?,?,?,?,?,?)',(quiz_id,telegram_id,score,total,json.dumps(answers,ensure_ascii=False),int(time.time())))
    def stats(self)->dict:
        with self._connect() as c:
            return {k:c.execute('SELECT COUNT(*) FROM '+k).fetchone()[0] for k in ('users','quizzes','results')}

store=Store()
