"""Deterministic policy engine. No AI model is called here. Pure function of the facts in PolicyContext."""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .cashflow import CashFlowResult
from .config import PolicyLimits
from .costs import Quote
from .models import OUTCOME_RANK, Decision, Finding, PaymentDetails, norm_account, norm_text
from .registry import RegistryResult


@dataclass
class PolicyContext:
    instruction: PaymentDetails
    registry: RegistryResult
    limits: PolicyLimits
    today: date
    intent: Optional[PaymentDetails] = None
    intent_diffs: list = field(default_factory=list)
    quote: Optional[Quote] = None
    current_mid_rate: Optional[Decimal] = None
    cashflow: Optional[CashFlowResult] = None
    duplicate: bool = False
    daily_spent: Decimal = Decimal("0")


def params_hash(ctx: PolicyContext) -> str:
    """Hash of every payment-critical parameter. An authorization is bound to exactly this hash."""
    d = ctx.instruction
    q = ctx.quote
    payload = {**d.core(), "scenario": q.scenario_id if q else "", "total_src": str(q.total_src) if q else "",
               "mid_rate": str(q.mid_rate) if q else ""}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def evaluate(ctx: PolicyContext) -> Decision:
    F = []
    L, d, q, cf = ctx.limits, ctx.instruction, ctx.quote, ctx.cashflow

    def add(code, outcome, msg, **ev):
        F.append(Finding(code, outcome, msg, ev))

    # 1. Untrusted-document defence
    inj = list(d.injection_findings) + (list(ctx.intent.injection_findings) if ctx.intent else [])
    if inj:
        add("INJECTION", "HOLD", "The document contains text that tries to give instructions to the system. "
            "It was ignored and cannot change any rule; a person must review the document.", snippets=inj)
    else:
        add("INJECTION", "ALLOW", "No instruction-like text found in the document.")

    # 2. Completeness / consistency
    if d.missing or d.inconsistencies:
        add("INCOMPLETE_OR_INCONSISTENT", "HOLD", "Required details are missing or contradict each other, "
            "so the payment cannot be verified.", missing=d.missing, inconsistencies=d.inconsistencies)
    else:
        add("INCOMPLETE_OR_INCONSISTENT", "ALLOW", "All required details are present and consistent.")

    # 3. Recipient verification against trusted registry
    r = ctx.registry
    if r.status == "MISMATCH":
        add("BENEFICIARY_MISMATCH", "BLOCK", "The payment details do not match the trusted record for this "
            "institution. This is a classic sign of payment redirection fraud. Execution is blocked until the "
            "institution confirms the change through an independent channel and an administrator updates the registry.",
            institution=r.institution, diffs=r.diffs)
    elif r.status == "NAME_MISMATCH":
        add("BENEFICIARY_NAME_MISMATCH", "HOLD", "The account matches the trusted record but the name or currency "
            "differs. Please verify before paying.", diffs=r.diffs)
    elif r.status == "UNVERIFIED":
        add("UNVERIFIED_BENEFICIARY", "HOLD", "This recipient is not in the trusted registry. It is UNVERIFIED "
            "(not proven safe, not proven fraudulent). Verify it with the institution through an independent channel.",
            institution=d.institution)
    else:
        add("BENEFICIARY_VERIFIED", "ALLOW", "Recipient details match the trusted registry record "
            f"({r.source}).", institution=r.institution)

    # 4. Payment Intent Fingerprint: instruction vs original invoice
    if ctx.intent is not None:
        crit = [x for x in ctx.intent_diffs if x["severity"] == "critical"]
        mat = [x for x in ctx.intent_diffs if x["severity"] != "critical"]
        if crit:
            add("INTENT_CHANGED_CRITICAL", "BLOCK", "Recipient details differ from the original invoice.", diffs=crit)
        elif mat:
            add("INTENT_CHANGED", "HOLD", "Amount, currency, reference or institution differ from the original invoice.",
                diffs=mat)
        else:
            add("INTENT_MATCH", "ALLOW", "Instruction matches the original invoice fingerprint.")

    # 5. Duplicate
    if ctx.duplicate:
        add("DUPLICATE_INVOICE", "BLOCK", "This invoice has already been paid in the sandbox. Paying twice is refused.")
    else:
        add("DUPLICATE_INVOICE", "ALLOW", "No earlier payment found for this invoice.")

    # 6. Deadline
    if d.due_date and d.due_date < ctx.today:
        add("DEADLINE_PASSED", "HOLD", f"The invoice due date {d.due_date} has passed; confirm with the institution "
            "that it still accepts payment.")

    # 7-9. Money checks need a quote
    if q is None:
        add("NO_QUOTE", "HOLD", "A cost estimate could not be produced (missing amount, currency, or rate).")
    else:
        total = q.total_src
        if total > L.per_transaction_limit:
            add("OVER_TX_LIMIT", "BLOCK", f"Total cost {total} {q.src_currency} exceeds the per-transaction limit "
                f"{L.per_transaction_limit}.", total=str(total), limit=str(L.per_transaction_limit))
        else:
            add("OVER_TX_LIMIT", "ALLOW", "Within the per-transaction limit.")
        if ctx.daily_spent + total > L.daily_limit:
            add("OVER_DAILY_LIMIT", "BLOCK", "This payment would exceed the daily limit.",
                spent_today=str(ctx.daily_spent), limit=str(L.daily_limit))
        if q.cost_pct > L.fee_block_pct:
            add("EXCESSIVE_FEES", "BLOCK", f"Fees and FX margin are {q.cost_pct}% over the mid-market value, above the "
                f"hard cap of {L.fee_block_pct}%.", cost_pct=str(q.cost_pct))
        elif q.cost_pct > L.fee_hold_pct:
            add("EXCESSIVE_FEES", "HOLD", f"Fees and FX margin are {q.cost_pct}% over the mid-market value "
                f"(review threshold {L.fee_hold_pct}%). A cheaper option may exist.", cost_pct=str(q.cost_pct))
        else:
            add("EXCESSIVE_FEES", "ALLOW", f"Cost is {q.cost_pct}% over the mid-market value, within limits.")
        if ctx.current_mid_rate is not None and q.mid_rate > 0:
            move = abs(ctx.current_mid_rate - q.mid_rate) / q.mid_rate * Decimal("100")
            if move > L.rate_move_hold_pct:
                add("RATE_MOVED", "HOLD", f"The exchange rate moved {move:.2f}% since the quote. Re-quote before paying.",
                    quoted=str(q.mid_rate), current=str(ctx.current_mid_rate))
            else:
                add("RATE_MOVED", "ALLOW", "Exchange rate is still within tolerance of the quote.")
        if cf is not None:
            if cf.balance < cf.payment:
                add("INSUFFICIENT_FUNDS", "BLOCK", f"Available funds {cf.balance} are less than the total cost "
                    f"{cf.payment}.")
            elif cf.status == "SHORTFALL":
                add("CASHFLOW_SHORTFALL", "HOLD", "The payment itself is covered, but afterwards you could not pay your "
                    f"upcoming essentials (first shortfall: {cf.first_negative}).",
                    remaining=str(cf.remaining_after), max_affordable=str(cf.max_affordable_payment))
            elif cf.status == "TIGHT":
                add("CASHFLOW_TIGHT", "HOLD", f"After this payment and listed essentials only {cf.remaining_after} "
                    f"would remain, below your safety buffer of {cf.buffer}.", remaining=str(cf.remaining_after))
            else:
                add("CASHFLOW_SAFE", "ALLOW", f"{cf.remaining_after} would remain after the payment and listed essentials.")

    outcome = max((f.outcome for f in F), key=lambda o: OUTCOME_RANK[o])
    ph = params_hash(ctx)
    return Decision(outcome, F, ph, ph[:12])
