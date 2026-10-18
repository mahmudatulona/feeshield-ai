"""FeeShield AI - Streamlit demo UI.  Run:  streamlit run app.py
All decisions come from the deterministic engine in feeshield/. SANDBOX ONLY - no real money moves."""
import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal

import streamlit as st

from feeshield import extractor
from feeshield.agent import FeeShieldAgent
from feeshield.cashflow import Expense
from feeshield.clock import Clock
from feeshield.costs import SCENARIOS
from feeshield.llm import extract_with_llm, llm_available

ROOT = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(ROOT, "data", "samples")
BADGE = {"ALLOW": "🟢 ALLOW", "HOLD": "🟡 HOLD", "BLOCK": "🔴 BLOCK"}

st.set_page_config(page_title="FeeShield AI", page_icon="🛡️", layout="wide")
st.title("🛡️ FeeShield AI")
st.caption("Safer cross-border student payments: recipient check + true cost + cash-flow safety + "
           "independent policy enforcement. SANDBOX with synthetic data - no real money moves.")

if "agent" not in st.session_state:
    llm_fn = extract_with_llm if llm_available() else None
    st.session_state.agent = FeeShieldAgent(db_path=":memory:", clock=Clock(scenario_date=date(2026, 10, 18)),
                                            llm_fn=llm_fn)
    st.session_state.update(inv=None, ins=None, ev=None, token=None, result=None)
agent = st.session_state.agent


def sample_text(name):
    with open(os.path.join(SAMPLES, name), encoding="utf-8") as fh:
        return fh.read()


with st.sidebar:
    st.header("Your finances (Step 3)")
    funds = st.number_input("Available funds (USD)", value=2000.00, step=50.0)
    rent = st.number_input("Rent due 25 Oct (USD)", value=400.00, step=50.0)
    other = st.number_input("Other essentials within 30 days (USD)", value=0.0, step=25.0)
    st.caption("Only expenses you list are counted. Future income is never assumed.")
    st.divider()
    st.write("**AI usage:** extraction uses " + ("rules + Claude assist (grounded)" if agent.llm_fn else
             "deterministic rules only (no API key set)") + ". Decisions, costs and limits are always deterministic code.")
    st.write("Sandbox balance:", f"{agent.bank.balance()} USD")
    if st.button("Reset session"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

expenses = [Expense("Rent", Decimal(str(rent)), date(2026, 10, 25))]
if other:
    expenses.append(Expense("Other essentials", Decimal(str(other)), date(2026, 10, 28)))

st.subheader("Step 1-2: Upload invoice → payment-intent record")
c1, c2 = st.columns(2)
up = c1.file_uploader("Invoice (.txt or .pdf)", type=["txt", "pdf"])
if c2.button("Load sample Northfield invoice"):
    st.session_state.inv = agent.ingest_invoice(sample_text("invoice_northfield.txt"))
    st.session_state.ev = None
if up is not None and st.button("Analyse uploaded invoice"):
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(up.name)[1]) as tmp:
        tmp.write(up.getvalue())
    st.session_state.inv = agent.ingest_invoice(extractor.read_document(tmp.name))
    os.unlink(tmp.name)
    st.session_state.ev = None
inv = st.session_state.inv
if inv:
    st.json(inv.safe_summary())
    if inv.injection_findings:
        st.warning("Instruction-like text found in the document and ignored: " + "; ".join(inv.injection_findings))
    st.caption(f"Intent fingerprint {inv.fingerprint()[:16]}… · extraction: {inv.extraction_method}")

    st.subheader("Step 4-5: Compare scenarios (sample cost data)")
    results = agent.compare_scenarios(inv, funds, expenses)
    rows = []
    for sid, ev in results.items():
        q, cf = ev.quote, ev.cashflow
        if q:
            rows.append({"Option": q.scenario_name, "You pay (USD)": str(q.total_src), "Fees (USD)": str(q.fee_src),
                         "Cost over mid-market %": str(q.cost_pct), "Recipient gets": f"{q.target_net_dest} {q.dst_currency}",
                         "Arrives": q.delivery, "Left after essentials": str(cf.remaining_after), "Cash-flow": cf.status,
                         "Decision": BADGE[ev.decision.outcome]})
    st.dataframe(rows, use_container_width=True)
    st.caption("⚠️ " + (results["bank_wire"].quote.data_label if results["bank_wire"].quote else ""))
    labels = {s.id: s.name for s in SCENARIOS}
    choice = st.radio("Choose an option to inspect", list(labels), format_func=lambda k: labels[k], horizontal=True)
    ev = results[choice]
    st.session_state.ev = ev
    st.markdown(f"### {BADGE[ev.decision.outcome]}")
    st.code(ev.explanation)
    if ev.cashflow:
        with st.expander("Cash-flow timeline"):
            for when, what, bal in ev.cashflow.timeline:
                st.write(f"{when} · {what} → balance {bal}")
            st.write(f"Max affordable payment with buffer: {ev.cashflow.max_affordable_payment}")

    st.subheader("Step 6: Paste a second payment instruction (e.g. an email)")
    if st.button("Load sample 'changed bank details' email"):
        st.session_state.ins_text = sample_text("instruction_changed_beneficiary.txt")
    ins_text = st.text_area("Instruction text", key="ins_text", height=170)
    if st.button("Check this instruction") and ins_text.strip():
        ins = agent.ingest_instruction(ins_text)
        iev = agent.evaluate(ins, choice, funds, expenses)
        st.markdown(f"### {BADGE[iev.decision.outcome]}")
        st.code(iev.explanation)

    st.subheader("Step 8: Authorize and execute in the sandbox")
    if ev.decision.outcome == "ALLOW":
        phrase = agent.auth.required_phrase(ev.decision)
        typed = st.text_input(f"Type **{phrase}** to authorize this exact payment")
        a, b, c = st.columns(3)
        if a.button("Authorize"):
            st.session_state.token = agent.authorize(ev, typed)
            st.success("Authorization issued (expires in 5 min)") if st.session_state.token else st.error("Phrase incorrect")
        if b.button("Execute in sandbox"):
            st.session_state.result = agent.execute(ev, st.session_state.token)
        if c.button("Revoke authorization") and st.session_state.token:
            agent.revoke(st.session_state.token)
            st.info("Authorization revoked")
    else:
        st.info("Execution is unavailable while the decision is " + ev.decision.outcome + ".")
        if st.button("Try to execute anyway (shows enforcement)"):
            st.session_state.result = agent.execute(ev, None)
    res = st.session_state.result
    if res:
        (st.success if res.status == "EXECUTED" else st.error)(f"{res.status}: {res.reason} {res.receipt}")

st.subheader("Audit log (accounts masked, hash-chained)")
st.caption("Chain valid: " + str(agent.audit.verify()))
st.dataframe([{k: e[k] for k in ("seq", "ts", "event", "actor", "data")} for e in agent.audit.entries()][::-1],
             use_container_width=True)
