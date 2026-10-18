"""Payment Intent Fingerprint comparison: invoice (intent) vs a later payment instruction."""
from .models import PaymentDetails, mask_account, norm_account, norm_text

CRITICAL = ("account", "bic", "beneficiary_name")
MATERIAL = ("amount", "currency", "invoice_ref", "institution", "due_date")


def diff_intent(intent: PaymentDetails, other: PaymentDetails) -> list:
    a, b = intent.core(), other.core()
    out = []
    for f in CRITICAL + MATERIAL:
        if b[f] == "" and f in ("bic", "due_date"):
            continue  # optional fields: absence is not a change
        if a[f] != b[f]:
            exp, obs = a[f], b[f] or "(missing)"
            if f == "account":
                exp, obs = mask_account(exp), mask_account(obs) or "(missing)"
            out.append({"field": f, "expected": exp, "observed": obs,
                        "severity": "critical" if f in CRITICAL else "material"})
    return out
