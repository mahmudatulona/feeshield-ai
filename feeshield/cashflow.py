"""Short-term cash-flow safety. Only listed essential expenses are counted; income that is
not guaranteed is NEVER assumed."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal


@dataclass
class Expense:
    name: str
    amount: Decimal
    due: date


@dataclass
class CashFlowResult:
    status: str                      # SAFE | TIGHT | SHORTFALL
    balance: Decimal
    payment: Decimal
    essentials_total: Decimal
    remaining_after: Decimal
    buffer: Decimal
    max_affordable_payment: Decimal
    timeline: list = field(default_factory=list)
    first_negative: str = ""
    counted: list = field(default_factory=list)
    ignored: list = field(default_factory=list)


def analyze(balance, payment, expenses, today, horizon_days, buffer) -> CashFlowResult:
    horizon_end = today + timedelta(days=horizon_days)
    counted = sorted([e for e in expenses if e.due <= horizon_end], key=lambda e: e.due)
    ignored = [e for e in expenses if e.due > horizon_end]
    essentials = sum((e.amount for e in counted), Decimal("0"))
    running = balance - payment
    timeline = [("today", "Pay tuition (all-in cost)", running)]
    first_neg = ""
    for e in counted:
        running -= e.amount
        timeline.append((e.due.isoformat(), e.name, running))
        if running < 0 and not first_neg:
            first_neg = f"{e.due.isoformat()} ({e.name})"
    remaining = balance - payment - essentials
    if balance < payment or remaining < 0:
        status = "SHORTFALL"
    elif remaining < buffer:
        status = "TIGHT"
    else:
        status = "SAFE"
    return CashFlowResult(status, balance, payment, essentials, remaining, buffer,
                          max(Decimal("0"), balance - essentials - buffer), timeline, first_neg,
                          counted, ignored)
