# Technical documentation - FeeShield AI

## 1. Workflow
1. **Ingest invoice** (`extractor.py`): label-based parser (txt/PDF) -> `PaymentDetails` = **Payment Intent Fingerprint** (SHA-256 over institution, reference, beneficiary, account, BIC, amount, currency, due date). Raw text is hashed, not stored.
2. **Ingest later instruction** (email text) the same way; `intent.diff_intent` lists changed fields (critical: account/BIC/beneficiary name; material: amount/currency/reference/institution/due date).
3. **Registry check** (`registry.py`): VERIFIED / NAME_MISMATCH / MISMATCH / UNVERIFIED against a small synthetic trusted registry. Unknown = *unverified*, never "safe" or "fraud".
4. **Cost intelligence** (`costs.py`): for each sample provider, total source cost = (target + intermediary fee) / (mid x (1 - markup)) + flat + % fee; reports fee, FX margin, % over mid-market, delivery time, and the reverse "net received for a fixed budget". All `Decimal`. Rates/fees are labelled **ILLUSTRATIVE SAMPLE DATA**.
5. **Cash-flow** (`cashflow.py`): balance - all-in payment - listed essentials within 30 days; SAFE / TIGHT (< buffer) / SHORTFALL; running timeline, first negative date, max affordable payment. No unlisted income assumed.
6. **Policy engine** (`policy.py`): pure function; every check emits a finding; worst outcome wins. BLOCK: recipient mismatch, critical intent change, duplicate, over per-transaction/daily limit, insufficient funds, fee hard cap. HOLD: injection text, missing/inconsistent data, unverified recipient, material intent change, overdue invoice, fees above review threshold, rate moved > 1%, tight/shortfall cash-flow.
7. **Authorization** (`execution.py`): token only issued for an ALLOW decision after the user types `AUTHORIZE <first 6 hex of params hash>`; single use, 5-minute expiry, bound to the exact parameters, revocable.
8. **Gateway** re-derives duplicate/daily-spend facts, re-runs the policy, validates the token, checks sandbox balance, then debits and logs.
9. **Audit** (`audit.py`): hash-chained rows, account numbers masked, `verify()` detects edits.

## 2. What uses AI vs rules
| Function | Method |
|---|---|
| Field extraction | Deterministic rules (default). Optional Claude assist fills only missing text fields and is grounding-checked. **The LLM path has not been run in the offline test environment; only the grounding filter is tested with a fake model.** |
| Prompt-injection detection | Regex patterns (heuristic, bypassable - see security doc) |
| Costs, cash-flow, policy, authorization, execution | Deterministic Python |
| Explanations | Deterministic templates built from findings (not an LLM) |

## 3. Core security design
Separation of duties: the agent builds *facts*; the policy engine decides; the gateway enforces. Limits are a frozen dataclass; documents cannot change them. See `SECURITY_SELF_ASSESSMENT.md`.
