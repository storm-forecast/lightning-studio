"""Persistent local job records and unique scheduling slots."""
import json
from pathlib import Path
import sqlite3

class JobStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, slot TEXT UNIQUE, payload TEXT NOT NULL)')

    def connection(self):
        return sqlite3.connect(self.path,timeout=30)

    def add(self,payload,slot=None):
        with self.connection() as db:
            result=db.execute('INSERT OR IGNORE INTO jobs(id,slot,payload) VALUES(?,?,?)',
                              (payload['id'],slot,json.dumps(payload,ensure_ascii=False)))
            if result.rowcount:return payload,True
            row=db.execute('SELECT payload FROM jobs WHERE slot=?',(slot,)).fetchone()
            if row is None:raise RuntimeError('conflito de identificador de job')
            return json.loads(row[0]),False

    def save(self,payload):
        with self.connection() as db:
            db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),payload['id']))

    def all(self):
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM jobs ORDER BY rowid')]
