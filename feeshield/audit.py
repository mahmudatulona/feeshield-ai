"""Tamper-evident audit log: each row stores the hash of the previous row.
Account numbers are masked before storage; raw documents are never logged."""
import hashlib
import json

from .models import mask_account

SENSITIVE_KEYS = ("account", "iban")


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS) and isinstance(v, str) and not v.startswith("****"):
                out[k] = mask_account(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(x) for x in obj]
    return obj


class AuditLog:
    def __init__(self, conn, clock):
        self.conn, self.clock = conn, clock
        conn.execute("""CREATE TABLE IF NOT EXISTS audit(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, event TEXT, actor TEXT,
            data TEXT, prev_hash TEXT, hash TEXT)""")
        conn.commit()

    def log(self, event: str, actor: str, data: dict) -> int:
        row = self.conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row["hash"] if row else "GENESIS"
        ts = self.clock.now().isoformat()
        payload = json.dumps(redact(data), sort_keys=True, default=str)
        h = hashlib.sha256(f"{prev}|{ts}|{event}|{actor}|{payload}".encode()).hexdigest()
        cur = self.conn.execute(
            "INSERT INTO audit(ts,event,actor,data,prev_hash,hash) VALUES (?,?,?,?,?,?)",
            (ts, event, actor, payload, prev, h))
        self.conn.commit()
        return cur.lastrowid

    def entries(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM audit ORDER BY seq")]

    def verify(self) -> bool:
        prev = "GENESIS"
        for r in self.conn.execute("SELECT * FROM audit ORDER BY seq"):
            h = hashlib.sha256(f"{prev}|{r['ts']}|{r['event']}|{r['actor']}|{r['data']}".encode()).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != h:
                return False
            prev = r["hash"]
        return True
