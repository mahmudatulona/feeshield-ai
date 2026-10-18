import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feeshield.agent import FeeShieldAgent
from feeshield.cashflow import Expense
from feeshield.clock import Clock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = date(2026, 10, 18)


def sample(name):
    with open(os.path.join(ROOT, "data", "samples", name), encoding="utf-8") as fh:
        return fh.read()


def make_agent(balance="2000.00", **kw):
    clock = Clock(fixed=datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc))
    return FeeShieldAgent(clock=clock, opening_balance=balance, **kw)


def expenses(rent="400.00"):
    return [Expense("Rent", Decimal(rent), date(2026, 10, 25))]


def run_valid(agent, scenario="fintech_a", funds="2000.00", exp=None):
    inv = agent.ingest_invoice(sample("invoice_northfield.txt"))
    return inv, agent.evaluate(inv, scenario, funds, exp if exp is not None else expenses())
