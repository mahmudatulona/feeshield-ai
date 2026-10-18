# Security self-assessment (prototype - NOT production-secure)

## Permission tiers implemented
| Tier | Actor | Can | Cannot |
|---|---|---|---|
| 0 Untrusted | Invoice / email text | Supply data fields | Change rules, limits, approve anything |
| 1 Agent / model | Extractor, orchestrator | Read documents, propose evaluations, request execution | Issue tokens, edit registry or limits, bypass gateway |
| 2 Student | Human user | Type confirmation to authorize ALLOW decisions, revoke | Authorize HOLD/BLOCK decisions |
| 3 Administrator | Out-of-band reviewer | `admin_verify_beneficiary` after independent verification | (not exposed in the student UI) |
| 4 Gateway | Deterministic code | Debit sandbox account after policy + token checks | Execute without ALLOW + valid token |

## Mitigations (each covered by a test)
Recipient mismatch -> BLOCK · unknown -> HOLD (unverified) · embedded instructions detected, ignored, force HOLD · limits frozen · money in `Decimal` · typed explicit authorization · single-use/expiring/revocable/hash-bound tokens · duplicate invoice refused · masked, tamper-evident audit · no secrets in repo (`.env` ignored, key via environment).

## Known risks and limitations (honest list)
1. Registry, rates, fees, and "verification" are **synthetic**; nothing was verified with a real institution or bank.
2. Everything runs in one process: a compromised process could bypass the "separate" layers. Production needs separate services/keys/HSM.
3. Typed-phrase authorization is not strong authentication (no MFA, no user accounts).
4. Injection detection is regex-based and can be evaded; the real protection is that document text is never authority, not the detector.
5. Rule-based extraction handles `Label: value` documents only; scanned PDFs (no OCR) and free-form layouts are unsupported unless the optional LLM assist is configured (untested here).
6. SQLite audit chain proves tamper *evidence* only if the latest hash is anchored externally; it is not.
7. Daily-limit accounting uses the sandbox ledger and the scenario date; no timezone handling.
8. No real sanctions/AML screening, no regulatory compliance claims.
9. The Streamlit UI was written but could not be launched in the build environment (no package access); the engine/tests/demo were run.
