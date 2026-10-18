"""End-to-end FeeShield demo (the 8 steps). Real run -> evidence/ files. Usage: python demo.py"""
import io
import json
import os
import sys
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from decimal import Decimal

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from feeshield.agent import FeeShieldAgent
from feeshield.cashflow import Expense
from feeshield.clock import Clock

D = Decimal


def sample(n):
    return open(os.path.join(ROOT, "data", "samples", n), encoding="utf-8").read()


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def main():
    db = os.path.join(ROOT, "evidence", "demo_sandbox.db")
    if os.path.exists(db):
        os.remove(db)
    agent = FeeShieldAgent(db_path=db, clock=Clock(scenario_date=date(2026, 10, 18)), opening_balance="2000.00")
    exp = [Expense("Rent", D("400.00"), date(2026, 10, 25))]
    print(f"FeeShield AI demo run at {datetime.now(timezone.utc).isoformat()} (SANDBOX / synthetic data only)")

    hr("STEP 1-2: Upload tuition invoice -> payment-intent record")
    inv = agent.ingest_invoice(sample("invoice_northfield.txt"))
    print(json.dumps(inv.safe_summary(), indent=2))
    print("Intent fingerprint:", inv.fingerprint()[:24], "...  extraction:", inv.extraction_method)

    hr("STEP 3: Student enters funds and upcoming essentials")
    print("Available funds: 2000.00 USD | Rent due 2026-10-25: 400.00 USD (listed income: none assumed)")

    hr("STEP 4-5: Registry check, cost estimate, decision (bank wire vs fintech A vs card B)")
    results = agent.compare_scenarios(inv, "2000.00", exp)
    for sid, ev in results.items():
        q, cf = ev.quote, ev.cashflow
        print(f"- {q.scenario_name}: pay {q.total_src} USD (fees {q.fee_src}, {q.cost_pct}% over mid-market) "
              f"-> recipient gets {q.target_net_dest} GBP in {q.delivery}; remaining after rent {cf.remaining_after} "
              f"[{cf.status}]  => {ev.decision.outcome}")
    print("\n" + results["bank_wire"].explanation)
    print("\nData label:", results["bank_wire"].quote.data_label)

    hr("STEP 6: Second payment instruction with CHANGED BENEFICIARY")
    ins = agent.ingest_instruction(sample("instruction_changed_beneficiary.txt"))
    bad = agent.evaluate(ins, "fintech_a", "2000.00", exp)
    print(bad.explanation)
    tok = agent.authorize(bad, "AUTHORIZE " + bad.decision.params_hash[:6].upper())
    print("\nAttempt to authorize the blocked instruction ->", tok)
    res = agent.execute(bad, "AUTH-ATTEMPT")
    print("Attempt to execute anyway ->", res.status, "|", res.reason)

    hr("STEP 7: Alternative valid scenario (original verified beneficiary, Fintech A)")
    good = results["fintech_a"]
    print(good.explanation)
    cf = good.cashflow
    print("\nCash-flow timeline:")
    for when, what, bal in cf.timeline:
        print(f"  {when:>12}  {what:<28} balance {bal}")
    print(f"Max affordable payment keeping a {cf.buffer} buffer: {cf.max_affordable_payment}")

    hr("STEP 8: Authorized sandbox execution")
    print("Without authorization ->", agent.execute(good, None).reason)
    phrase = agent.auth.required_phrase(good.decision)
    print("Student types:", phrase)
    token = agent.authorize(good, phrase)
    print("Authorization token:", token)
    res = agent.execute(good, token)
    print("Result:", res.status, "|", res.reason, "| receipt:", res.receipt)
    print("Sandbox balance after:", agent.bank.balance())
    print("Replay of same token ->", agent.execute(good, token).reason)
    ev_dup = agent.evaluate(inv, "fintech_a", agent.bank.balance(), [])
    print("Paying same invoice again ->", ev_dup.decision.outcome, [f.code for f in ev_dup.decision.failed])

    hr("AUDIT LOG (accounts masked) - hash chain valid: %s" % agent.audit.verify())
    for e in agent.audit.entries():
        print(f"#{e['seq']:>2} {e['ts'][:19]} {e['event']:<22} {e['actor']:<14} {e['data'][:150]}")


if __name__ == "__main__":
    buf = io.StringIO()

    class Tee:
        def write(self, s):
            sys.__stdout__.write(s)
            buf.write(s)

        def flush(self):
            sys.__stdout__.flush()

    sys.stdout = Tee()
    main()
    sys.stdout = sys.__stdout__
    with open(os.path.join(ROOT, "evidence", "demo_run_log.txt"), "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
