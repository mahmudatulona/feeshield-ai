# FeeShield AI

Sandbox AI financial agent for international students (2026 Shenzhen International FinTech Competition, International Track, **Topic C**).
It answers three questions before a cross-border payment: *Is the recipient the intended, verified one? What will it really cost? Can I afford it given upcoming essentials?* — and a separate policy engine decides **ALLOW / HOLD / BLOCK**.

> SANDBOX ONLY. Synthetic data. No real bank, no real money. Not production-secure (see `docs/SECURITY_SELF_ASSESSMENT.md`).

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_tests.py          # or: pytest -q      (30 tests; writes docs/TEST_RESULTS.md)
python demo.py               # 8-step end-to-end demo; writes evidence/demo_run_log.txt
streamlit run app.py         # interactive UI (http://localhost:8501)
```
Only the Python standard library is needed for the engine, tests and demo (`pdfplumber` for PDF invoices, `streamlit` for the UI).

## Optional AI-assisted extraction
```bash
pip install anthropic
export ANTHROPIC_API_KEY=...        # never commit keys; .env is git-ignored
export FEESHIELD_MODEL=claude-sonnet-5-5   # optional override
```
Without a key the app runs on deterministic rule-based extraction. The AI path only *suggests* fields the rules missed, and any value not literally present in the document is discarded. Costs, risk checks, limits and execution are always deterministic code.

## Layout
`feeshield/` extractor, registry, intent, costs, cashflow, policy, execution (sandbox bank + authorization + gateway), audit, agent · `app.py` UI · `demo.py` · `tests/` · `data/samples/` · `docs/` · `evidence/`

## Troubleshooting
- `ModuleNotFoundError: feeshield` → run commands from the repository root.
- PDF invoice returns no text → scanned image PDFs are unsupported (no OCR).
- Streamlit port busy → `streamlit run app.py --server.port 8502`.
