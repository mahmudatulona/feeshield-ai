"""Orchestrator: wires extraction -> registry -> cost -> cash-flow -> policy -> authorization -> sandbox."""
import dataclasses
from decimal import Decimal
from typing import Optional

from . import cashflow as cf_mod
from . import costs, extractor
from .audit import AuditLog
from .clock import Clock
from .config import PolicyLimits
from .db import connect
from .execution import AuthorizationService, ExecutionGateway, SandboxBank
from .explain import explain
from .intent import diff_intent
from .models import PaymentDetails
from .policy import PolicyContext, evaluate
from .registry import TrustedRegistry


@dataclasses.dataclass
class Evaluation:
    ctx: PolicyContext
    decision: object
    explanation: str
    quote: Optional[costs.Quote]
    cashflow: Optional[cf_mod.CashFlowResult]


class FeeShieldAgent:
    def __init__(self, db_path=":memory:", limits: PolicyLimits = None, clock: Clock = None,
                 rates: costs.RateTable = None, opening_balance="2000.00", llm_fn=None):
        self.limits = limits or PolicyLimits()
        self.clock = clock or Clock()
        self.rates = rates or costs.RateTable()
        self.conn = connect(db_path)
        self.audit = AuditLog(self.conn, self.clock)
        self.registry = TrustedRegistry(self.conn, self.clock)
        self.bank = SandboxBank(self.conn, self.clock, self.limits.account_currency, opening_balance)
        self.auth = AuthorizationService(self.conn, self.clock, self.limits.authorization_ttl_seconds)
        self.gateway = ExecutionGateway(self.bank, self.auth, self.audit, self.clock)
        self.llm_fn = llm_fn
        self.intent: Optional[PaymentDetails] = None
        self.audit.log("SESSION_START", "system", {"limits_fingerprint": self.limits.fingerprint(),
                                                   "ai_extraction": "enabled" if llm_fn else "disabled"})

    # ---- Steps 1-2: intent record
    def ingest_invoice(self, text: str) -> PaymentDetails:
        d = extractor.extract(text, "invoice", self.llm_fn)
        self.intent = d
        self.audit.log("INVOICE_INGESTED", "agent", {
            "fingerprint": d.fingerprint()[:16], "summary": d.safe_summary(), "method": d.extraction_method,
            "missing": d.missing, "injection_hits": len(d.injection_findings)})
        return d

    def ingest_instruction(self, text: str) -> PaymentDetails:
        d = extractor.extract(text, "instruction", self.llm_fn)
        self.audit.log("INSTRUCTION_INGESTED", "agent", {
            "fingerprint": d.fingerprint()[:16], "summary": d.safe_summary(),
            "missing": d.missing, "injection_hits": len(d.injection_findings)})
        return d

    # ---- Steps 3-5: evaluate
    def evaluate(self, instruction: PaymentDetails, scenario_id: str, funds, expenses, compare_to_intent=True) -> Evaluation:
        funds = Decimal(str(funds))
        L = self.limits
        q = None
        if instruction.amount is not None and instruction.currency:
            try:
                mid = self.rates.get(L.account_currency, instruction.currency)
                q = costs.quote(costs.SCENARIO_BY_ID[scenario_id], instruction.amount, L.account_currency,
                                instruction.currency, mid, self.rates.as_of)
            except KeyError:
                q = None
        cf = None
        if q is not None:
            cf = cf_mod.analyze(funds, q.total_src, expenses, self.clock.today(), L.expense_horizon_days, L.min_cash_buffer)
        intent = self.intent if compare_to_intent else None
        key = instruction.core()["institution"] + "|" + instruction.core()["invoice_ref"]
        ctx = PolicyContext(
            instruction=instruction, registry=self.registry.check(instruction), limits=L, today=self.clock.today(),
            intent=intent, intent_diffs=diff_intent(intent, instruction) if intent else [],
            quote=q, current_mid_rate=q.mid_rate if q else None, cashflow=cf,
            duplicate=self.bank.has_paid(key), daily_spent=self.bank.spent_today(self.clock.today()))
        dec = evaluate(ctx)
        self.audit.log("POLICY_DECISION", "policy_engine", {
            "outcome": dec.outcome, "scenario": scenario_id, "params_hash": dec.params_hash[:12],
            "failed_rules": [f.code for f in dec.failed],
            "total_cost": str(q.total_src) if q else None})
        return Evaluation(ctx, dec, explain(dec), q, cf)

    def compare_scenarios(self, instruction, funds, expenses):
        return {s.id: self.evaluate(instruction, s.id, funds, expenses) for s in costs.SCENARIOS}

    # ---- Step 8: authorize + execute
    def authorize(self, ev: Evaluation, typed_phrase: str) -> Optional[str]:
        tid = self.auth.issue(ev.decision, typed_phrase)
        self.audit.log("AUTHORIZATION_" + ("ISSUED" if tid else "DENIED"), "student",
                       {"params_hash": ev.decision.params_hash[:12], "outcome_at_request": ev.decision.outcome,
                        "token": tid})
        return tid

    def revoke(self, token_id: str):
        self.auth.revoke(token_id)
        self.audit.log("AUTHORIZATION_REVOKED", "student", {"token": token_id})

    def execute(self, ev: Evaluation, token_id: Optional[str]):
        q = ev.ctx.quote
        ctx = dataclasses.replace(ev.ctx, current_mid_rate=(
            self.rates.get(q.src_currency, q.dst_currency) if q else None))
        return self.gateway.execute(ctx, token_id)

    # ---- Administrative (out-of-band) action, deliberately NOT callable by the model
    def admin_verify_beneficiary(self, display, aliases, beneficiary, account, bic, currency, verified_by, method):
        self.registry.add_verified(display, aliases, beneficiary, account, bic, currency,
                                   source=f"admin-verified by {verified_by} via {method}")
        self.audit.log("REGISTRY_UPDATED", "admin:" + verified_by, {"institution": display, "method": method,
                                                                   "account": account})
