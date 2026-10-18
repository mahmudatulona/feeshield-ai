"""Sandbox bank, authorization service and execution gateway.

The gateway is the ONLY code path that moves (simulated) money. It re-runs the deterministic policy
itself, verifies a single-use authorization bound to the exact parameters, and refuses otherwise.
The AI/agent layer can request execution but cannot issue tokens, edit limits, or skip these checks."""
import dataclasses
import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .models import Decision
from .policy import PolicyContext, evaluate


class SandboxBank:
    def __init__(self, conn, clock, currency="USD", opening_balance="2000.00"):
        self.conn, self.clock, self.currency = conn, clock, currency
        conn.execute("CREATE TABLE IF NOT EXISTS account(id INTEGER PRIMARY KEY, balance TEXT, currency TEXT)")
        conn.execute("""CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
            receipt TEXT, invoice_key TEXT UNIQUE, amount TEXT, dest TEXT, params_hash TEXT)""")
        if conn.execute("SELECT COUNT(*) c FROM account").fetchone()["c"] == 0:
            conn.execute("INSERT INTO account VALUES (1,?,?)", (opening_balance, currency))
        conn.commit()

    def balance(self) -> Decimal:
        return Decimal(self.conn.execute("SELECT balance FROM account WHERE id=1").fetchone()["balance"])

    def set_balance(self, v):  # test/demo helper: simulated account only
        self.conn.execute("UPDATE account SET balance=? WHERE id=1", (str(Decimal(str(v))),))
        self.conn.commit()

    def has_paid(self, invoice_key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM ledger WHERE invoice_key=?", (invoice_key,)).fetchone() is not None

    def spent_today(self, today) -> Decimal:
        rows = self.conn.execute("SELECT amount, ts FROM ledger").fetchall()
        return sum((Decimal(r["amount"]) for r in rows if r["ts"][:10] == today.isoformat()), Decimal("0"))

    def debit(self, amount: Decimal, invoice_key, dest, phash) -> str:
        receipt = "SBX-" + secrets.token_hex(5).upper()
        self.conn.execute("UPDATE account SET balance=? WHERE id=1", (str(self.balance() - amount),))
        self.conn.execute("INSERT INTO ledger(ts,receipt,invoice_key,amount,dest,params_hash) VALUES (?,?,?,?,?,?)",
                          (self.clock.now().isoformat(), receipt, invoice_key, str(amount), dest, phash))
        self.conn.commit()
        return receipt


class AuthorizationService:
    """Issues single-use, expiring tokens bound to a params_hash. Requires a typed human confirmation."""

    def __init__(self, conn, clock, ttl_seconds):
        self.conn, self.clock, self.ttl = conn, clock, ttl_seconds
        conn.execute("""CREATE TABLE IF NOT EXISTS tokens(id TEXT PRIMARY KEY, params_hash TEXT,
            expires_at TEXT, revoked INTEGER DEFAULT 0, used INTEGER DEFAULT 0)""")
        conn.commit()

    @staticmethod
    def required_phrase(decision: Decision) -> str:
        return "AUTHORIZE " + decision.params_hash[:6].upper()

    def issue(self, decision: Decision, typed_phrase: str) -> Optional[str]:
        if decision.outcome != "ALLOW":
            return None
        if (typed_phrase or "").strip().upper() != self.required_phrase(decision):
            return None
        tid = "AUTH-" + secrets.token_hex(6).upper()
        from datetime import timedelta
        exp = (self.clock.now() + timedelta(seconds=self.ttl)).isoformat()
        self.conn.execute("INSERT INTO tokens(id,params_hash,expires_at) VALUES (?,?,?)", (tid, decision.params_hash, exp))
        self.conn.commit()
        return tid

    def revoke(self, tid: str) -> None:
        self.conn.execute("UPDATE tokens SET revoked=1 WHERE id=?", (tid,))
        self.conn.commit()

    def check(self, tid: Optional[str], phash: str):
        if not tid:
            return False, "no authorization token supplied"
        r = self.conn.execute("SELECT * FROM tokens WHERE id=?", (tid,)).fetchone()
        if r is None:
            return False, "unknown authorization token"
        if r["revoked"]:
            return False, "authorization was revoked"
        if r["used"]:
            return False, "authorization already used"
        if r["expires_at"] < self.clock.now().isoformat():
            return False, "authorization expired"
        if r["params_hash"] != phash:
            return False, "payment terms changed since authorization"
        return True, "ok"

    def consume(self, tid):
        self.conn.execute("UPDATE tokens SET used=1 WHERE id=?", (tid,))
        self.conn.commit()


@dataclass
class ExecutionResult:
    status: str            # EXECUTED | REFUSED
    reason: str
    receipt: str = ""
    decision: Optional[Decision] = None


class ExecutionGateway:
    def __init__(self, bank: SandboxBank, auth: AuthorizationService, audit, clock):
        self.bank, self.auth, self.audit, self.clock = bank, auth, audit, clock

    def execute(self, ctx: PolicyContext, token_id: Optional[str]) -> ExecutionResult:
        d = ctx.instruction
        key = (d.core()["institution"] + "|" + d.core()["invoice_ref"])
        # Gateway re-derives facts it must not take on trust
        ctx = dataclasses.replace(ctx, duplicate=self.bank.has_paid(key),
                                  daily_spent=self.bank.spent_today(self.clock.today()))
        decision = evaluate(ctx)
        self.audit.log("EXECUTION_ATTEMPT", "gateway", {
            "invoice_key": key, "policy_outcome": decision.outcome, "params_hash": decision.params_hash[:12],
            "token_supplied": bool(token_id)})

        def refuse(reason):
            self.audit.log("EXECUTION_REFUSED", "gateway", {"reason": reason, "invoice_key": key})
            return ExecutionResult("REFUSED", reason, decision=decision)

        if decision.outcome != "ALLOW":
            return refuse(f"policy outcome is {decision.outcome}: " + "; ".join(f.code for f in decision.failed))
        ok, why = self.auth.check(token_id, decision.params_hash)
        if not ok:
            return refuse(why)
        total = ctx.quote.total_src
        if self.bank.balance() < total:
            return refuse("sandbox account balance is lower than the total cost")
        self.auth.consume(token_id)
        receipt = self.bank.debit(total, key, d.account or "", decision.params_hash)
        self.audit.log("EXECUTION_DONE", "gateway", {
            "receipt": receipt, "amount": str(total), "currency": ctx.quote.src_currency,
            "beneficiary_account": d.account, "invoice_key": key, "token": token_id,
            "balance_after": str(self.bank.balance())})
        return ExecutionResult("EXECUTED", "authorized sandbox transfer completed", receipt, decision)
