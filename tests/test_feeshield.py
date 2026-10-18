"""FeeShield AI test suite. Plain asserts - runs under pytest OR `python run_tests.py`."""
from datetime import timedelta
from decimal import Decimal

from helpers import TODAY, expenses, make_agent, run_valid, sample
from feeshield import extractor
from feeshield.audit import AuditLog
from feeshield.config import PolicyLimits
from feeshield.costs import SCENARIO_BY_ID, RateTable, net_received_for_budget, quote

D = Decimal


def codes(ev, outcome=None):
    return [f.code for f in ev.decision.findings if outcome is None or f.outcome == outcome]


# 1
def test_legitimate_invoice_verified_recipient_allows():
    a = make_agent()
    inv, ev = run_valid(a)
    assert inv.amount == D("1150.00") and inv.currency == "GBP"
    assert ev.decision.outcome == "ALLOW", ev.explanation
    assert "BENEFICIARY_VERIFIED" in codes(ev, "ALLOW")


# 2
def test_changed_beneficiary_is_blocked():
    a = make_agent()
    a.ingest_invoice(sample("invoice_northfield.txt"))
    ins = a.ingest_instruction(sample("instruction_changed_beneficiary.txt"))
    ev = a.evaluate(ins, "fintech_a", "2000", expenses())
    assert ev.decision.outcome == "BLOCK"
    assert "BENEFICIARY_MISMATCH" in codes(ev, "BLOCK") and "INTENT_CHANGED_CRITICAL" in codes(ev, "BLOCK")


# 3
def test_unknown_recipient_is_unverified_hold_not_block():
    a = make_agent()
    inv = a.ingest_invoice(sample("invoice_unknown_recipient.txt"))
    ev = a.evaluate(inv, "fintech_a", "2000", [])
    assert ev.decision.outcome == "HOLD"
    assert "UNVERIFIED_BENEFICIARY" in codes(ev, "HOLD")
    assert "BENEFICIARY_MISMATCH" not in codes(ev)


# 4
def test_modified_amount_holds():
    a = make_agent()
    a.ingest_invoice(sample("invoice_northfield.txt"))
    ins = a.ingest_instruction(sample("invoice_northfield.txt").replace("1,150.00", "1,250.00"))
    ev = a.evaluate(ins, "fintech_a", "2000", expenses())
    assert ev.decision.outcome == "HOLD" and "INTENT_CHANGED" in codes(ev, "HOLD")


# 5
def test_missing_invoice_reference_holds():
    a = make_agent()
    text = sample("invoice_northfield.txt").replace("Invoice No: NFU-2026-004571\n", "")
    inv = a.ingest_invoice(text)
    ev = a.evaluate(inv, "fintech_a", "2000", expenses())
    assert "invoice_ref" in inv.missing
    assert ev.decision.outcome == "HOLD" and "INCOMPLETE_OR_INCONSISTENT" in codes(ev, "HOLD")


# 6
def test_incorrect_invoice_reference_holds():
    a = make_agent()
    a.ingest_invoice(sample("invoice_northfield.txt"))
    ins = a.ingest_instruction(sample("invoice_northfield.txt").replace("NFU-2026-004571", "NFU-2026-009999"))
    ev = a.evaluate(ins, "fintech_a", "2000", expenses())
    assert ev.decision.outcome == "HOLD" and "INTENT_CHANGED" in codes(ev, "HOLD")


# 7
def test_duplicate_invoice_blocked_after_payment():
    a = make_agent()
    inv, ev = run_valid(a)
    tok = a.authorize(ev, a.auth.required_phrase(ev.decision))
    assert a.execute(ev, tok).status == "EXECUTED"
    ev2 = a.evaluate(inv, "fintech_a", a.bank.balance(), [])
    assert ev2.decision.outcome == "BLOCK" and "DUPLICATE_INVOICE" in codes(ev2, "BLOCK")


# 8
def test_malicious_embedded_instructions_cannot_override_rules():
    a = make_agent()
    inv = a.ingest_invoice(sample("invoice_malicious_injection.txt"))
    ev = a.evaluate(inv, "fintech_a", "2000", expenses())
    assert inv.injection_findings, "injection text must be detected"
    assert ev.decision.outcome == "HOLD" and "INJECTION" in codes(ev, "HOLD")
    assert a.limits.per_transaction_limit == D("2000.00")        # limit untouched by the document
    assert a.authorize(ev, "AUTHORIZE " + ev.decision.params_hash[:6]) is None  # cannot even get a token


# 9
def test_legitimate_invoice_has_no_false_injection_positive():
    d = extractor.extract(sample("invoice_northfield.txt"))
    assert d.injection_findings == []


# 10
def test_payment_over_authorization_limit_blocked():
    a = make_agent(balance="5000.00", limits=PolicyLimits(per_transaction_limit=D("1000.00")))
    inv, ev = run_valid(a, funds="5000", exp=[])
    assert ev.decision.outcome == "BLOCK" and "OVER_TX_LIMIT" in codes(ev, "BLOCK")


# 11
def test_legit_payment_creating_cashflow_shortfall_holds():
    a = make_agent()
    inv, ev = run_valid(a, funds="1700.00", exp=expenses("400.00"))   # 1700-1511.27 = 188.73 < 400 rent
    assert ev.cashflow.status == "SHORTFALL"
    assert ev.decision.outcome == "HOLD" and "CASHFLOW_SHORTFALL" in codes(ev, "HOLD")
    assert "BENEFICIARY_VERIFIED" in codes(ev, "ALLOW")           # recipient fine, affordability not
    assert "Rent" in ev.cashflow.first_negative


# 12
def test_tight_cashflow_below_buffer_holds():
    a = make_agent()
    inv, ev = run_valid(a, scenario="bank_wire")   # 2000-1570.12-400 = 29.88 < 50 buffer
    assert ev.cashflow.status == "TIGHT"
    assert "CASHFLOW_TIGHT" in codes(ev, "HOLD")


# 13
def test_excessive_fees_hold_and_hard_cap_block():
    a = make_agent()
    inv, ev = run_valid(a, scenario="bank_wire", funds="3000")
    assert ev.quote.cost_pct > D("3") and "EXCESSIVE_FEES" in codes(ev, "HOLD")
    a2 = make_agent(limits=PolicyLimits(fee_block_pct=D("4.00")))
    inv, ev2 = run_valid(a2, scenario="bank_wire", funds="3000")
    assert "EXCESSIVE_FEES" in codes(ev2, "BLOCK") and ev2.decision.outcome == "BLOCK"


# 14
def test_exchange_rate_change_after_quote_holds_execution():
    a = make_agent()
    inv, ev = run_valid(a)
    tok = a.authorize(ev, a.auth.required_phrase(ev.decision))
    a.rates.set("USD", "GBP", "0.7500")             # ~2.6% move
    res = a.execute(ev, tok)
    assert res.status == "REFUSED" and "RATE_MOVED" in res.reason
    assert a.bank.balance() == D("2000.00")


# 15
def test_amount_insufficient_after_fees_net_received():
    sc = SCENARIO_BY_ID["bank_wire"]
    net = net_received_for_budget(sc, D("1150.00"), "USD", "GBP", D("0.77"))
    assert net < D("1150.00") * D("0.77")           # fees + margin + intermediary fee reduce arrival
    q = quote(sc, D("1150.00"), "USD", "GBP", D("0.77"))
    assert net_received_for_budget(sc, q.total_src, "USD", "GBP", D("0.77")) == D("1150.00")
    a = make_agent(balance="1200")
    inv, ev = run_valid(a, funds="1200", exp=[])
    assert ev.decision.outcome == "BLOCK" and "INSUFFICIENT_FUNDS" in codes(ev, "BLOCK")


# 16
def test_missing_or_inconsistent_information_holds():
    a = make_agent()
    inv = a.ingest_invoice(sample("invoice_northfield.txt").replace("Currency: GBP", "Currency: USD"))
    assert any("conflicts" in i for i in inv.inconsistencies)
    ev = a.evaluate(inv, "fintech_a", "2000", expenses())
    assert ev.decision.outcome in ("HOLD", "BLOCK") and ev.decision.outcome != "ALLOW"
    inv2 = a.ingest_invoice("Institution: Northfield University\nAmount Due: GBP 1,150.00")
    ev2 = a.evaluate(inv2, "fintech_a", "2000", expenses())
    assert set(["invoice_ref", "account"]) <= set(inv2.missing) and ev2.decision.outcome != "ALLOW"


# 17
def test_execution_without_authorization_refused():
    a = make_agent()
    inv, ev = run_valid(a)
    res = a.execute(ev, None)
    assert res.status == "REFUSED" and "no authorization" in res.reason
    assert a.bank.balance() == D("2000.00")
    assert a.execute(ev, "AUTH-FORGED123").status == "REFUSED"


# 18
def test_authorization_requires_typed_confirmation():
    a = make_agent()
    inv, ev = run_valid(a)
    assert a.authorize(ev, "yes") is None
    assert a.authorize(ev, "AUTHORIZE 000000") is None
    assert a.authorize(ev, a.auth.required_phrase(ev.decision)) is not None


# 19
def test_successful_authorized_sandbox_transaction_and_audit():
    a = make_agent()
    inv, ev = run_valid(a)
    tok = a.authorize(ev, a.auth.required_phrase(ev.decision))
    res = a.execute(ev, tok)
    assert res.status == "EXECUTED" and res.receipt.startswith("SBX-")
    assert a.bank.balance() == D("2000.00") - ev.quote.total_src
    events = [e["event"] for e in a.audit.entries()]
    assert "EXECUTION_DONE" in events and a.audit.verify()
    # token is single use
    assert a.execute(ev, tok).status == "REFUSED"


# 20
def test_policy_rejection_cannot_be_authorized_or_executed():
    a = make_agent()
    a.ingest_invoice(sample("invoice_northfield.txt"))
    ins = a.ingest_instruction(sample("instruction_changed_beneficiary.txt"))
    ev = a.evaluate(ins, "fintech_a", "2000", expenses())
    assert ev.decision.outcome == "BLOCK"
    assert a.authorize(ev, "AUTHORIZE " + ev.decision.params_hash[:6].upper()) is None
    assert a.execute(ev, "AUTH-ANYTHING").status == "REFUSED"
    assert a.bank.balance() == D("2000.00")


# 21
def test_execution_after_authorization_revoked_refused():
    a = make_agent()
    inv, ev = run_valid(a)
    tok = a.authorize(ev, a.auth.required_phrase(ev.decision))
    a.revoke(tok)
    res = a.execute(ev, tok)
    assert res.status == "REFUSED" and "revoked" in res.reason
    assert a.bank.balance() == D("2000.00")


# 22
def test_expired_authorization_refused():
    a = make_agent()
    inv, ev = run_valid(a)
    tok = a.authorize(ev, a.auth.required_phrase(ev.decision))
    a.clock.advance(PolicyLimits().authorization_ttl_seconds + 1)
    assert "expired" in a.execute(ev, tok).reason


# 23
def test_authorization_is_bound_to_exact_terms():
    a = make_agent()
    inv, ev_a = run_valid(a, scenario="fintech_a")
    ev_b = a.evaluate(inv, "card_b", "2000", expenses())
    tok = a.authorize(ev_a, a.auth.required_phrase(ev_a.decision))
    res = a.execute(ev_b, tok)         # token for scenario A used for scenario B
    assert res.status == "REFUSED" and "changed" in res.reason


# 24
def test_limits_cannot_be_modified_at_runtime():
    a = make_agent()
    try:
        a.limits.per_transaction_limit = D("999999")
        raised = False
    except Exception:
        raised = True
    assert raised and a.limits.per_transaction_limit == D("2000.00")


# 25
def test_audit_log_masks_accounts_and_detects_tampering():
    a = make_agent()
    inv, ev = run_valid(a)
    raw = " ".join(e["data"] for e in a.audit.entries())
    assert "GB00NFLD00000000457123" not in raw and "NFLD0000" not in raw
    assert a.audit.verify()
    a.conn.execute("UPDATE audit SET data='{}' WHERE seq=2")
    assert a.audit.verify() is False


# 26
def test_admin_verification_resolves_unknown_beneficiary_hold():
    a = make_agent()
    inv = a.ingest_invoice(sample("invoice_unknown_recipient.txt"))
    ev = a.evaluate(inv, "fintech_a", "2000", [])
    assert ev.decision.outcome == "HOLD"
    a.admin_verify_beneficiary("Riverbend Language School", [], "Riverbend Language School Ltd",
                               "GB00RIVR00000000123456", "RIVRGB2L", "GBP", "reviewer1", "phone call to published number")
    ev2 = a.evaluate(inv, "fintech_a", "2000", [])
    assert ev2.decision.outcome == "ALLOW"


# 27
def test_pdf_invoice_extraction():
    import os
    from helpers import ROOT
    pdf = os.path.join(ROOT, "data", "samples", "invoice_northfield.pdf")
    d = extractor.extract(extractor.read_document(pdf))
    assert d.invoice_ref == "NFU-2026-004571" and d.amount == D("1150.00")


# 28
def test_llm_suggestions_are_grounded_in_document_text():
    fake = lambda text: {"invoice_ref": "INVENTED-123", "bic": "NFLDGB2L"}
    text = sample("invoice_northfield.txt").replace("Bank BIC/SWIFT: NFLDGB2L", "BIC code NFLDGB2L").replace(
        "Invoice No: NFU-2026-004571\n", "")
    d = extractor.extract(text, llm_fn=fake)
    assert d.bic == "NFLDGB2L" and "bic" in d.llm_filled      # present in the text -> accepted
    assert d.invoice_ref is None                              # hallucinated value discarded


# 29
def test_same_invoice_same_fingerprint_changed_field_changes_it():
    a = extractor.extract(sample("invoice_northfield.txt"))
    b = extractor.extract(sample("invoice_northfield.txt"))
    c = extractor.extract(sample("invoice_northfield.txt").replace("1,150.00", "1,151.00"))
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()


# 30
def test_cashflow_ignores_unlisted_income_and_counts_only_horizon():
    from datetime import date
    from feeshield.cashflow import Expense, analyze
    ex = [Expense("Rent", D("400"), date(2026, 10, 25)), Expense("Far", D("999"), TODAY + timedelta(days=90))]
    r = analyze(D("2000"), D("1511.27"), ex, TODAY, 30, D("50"))
    assert r.essentials_total == D("400") and len(r.ignored) == 1 and r.remaining_after == D("88.73")
