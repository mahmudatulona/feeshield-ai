from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

OUTCOME_RANK = {"ALLOW": 0, "HOLD": 1, "BLOCK": 2}


def norm_account(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isalnum()).upper()


def norm_text(s: Optional[str]) -> str:
    return " ".join((s or "").split()).upper()


def mask_account(s: Optional[str]) -> str:
    a = norm_account(s)
    return "" if not a else "****" + a[-4:]


@dataclass
class PaymentDetails:
    """What a document (invoice or later payment instruction) says. Also used as the 'intent' record."""
    kind: str = "invoice"                      # "invoice" | "instruction"
    institution: Optional[str] = None
    invoice_ref: Optional[str] = None
    beneficiary_name: Optional[str] = None
    account: Optional[str] = None
    bic: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    due_date: Optional[date] = None
    source_sha256: str = ""                    # hash only - raw document text is never stored
    extraction_method: str = "rules"
    injection_findings: list = field(default_factory=list)
    inconsistencies: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    llm_filled: list = field(default_factory=list)

    def core(self) -> dict:
        return {
            "institution": norm_text(self.institution),
            "invoice_ref": norm_account(self.invoice_ref),
            "beneficiary_name": norm_text(self.beneficiary_name),
            "account": norm_account(self.account),
            "bic": norm_account(self.bic),
            "amount": str(self.amount) if self.amount is not None else "",
            "currency": (self.currency or "").upper(),
            "due_date": self.due_date.isoformat() if self.due_date else "",
        }

    def fingerprint(self) -> str:
        """Payment Intent Fingerprint: stable hash of the payment-critical fields."""
        return hashlib.sha256(json.dumps(self.core(), sort_keys=True).encode()).hexdigest()

    def safe_summary(self) -> dict:
        d = self.core()
        d["account"] = mask_account(self.account)
        return d


@dataclass
class Finding:
    code: str
    outcome: str            # ALLOW (check passed) | HOLD | BLOCK
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Decision:
    outcome: str
    findings: list
    params_hash: str
    decision_id: str

    @property
    def failed(self):
        return [f for f in self.findings if f.outcome != "ALLOW"]

    @property
    def passed(self):
        return [f for f in self.findings if f.outcome == "ALLOW"]
