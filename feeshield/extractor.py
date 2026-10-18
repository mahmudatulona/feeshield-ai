"""Invoice / payment-instruction extraction.

DETERMINISTIC rule-based parser (always available). Optional LLM assist lives in llm.py and may only
fill fields the rules missed, and only if the value is literally present in the document.
Document text is DATA: instruction-like text is detected, reported, and never executed."""
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from .models import PaymentDetails

LABELS = {
    "institution": ["institution", "university", "payee institution", "issuer"],
    "invoice_ref": ["invoice no", "invoice number", "invoice ref", "invoice reference",
                    "payment reference", "reference", "invoice #"],
    "beneficiary_name": ["beneficiary name", "beneficiary", "account name", "payee"],
    "account": ["beneficiary account (iban)", "beneficiary account", "iban", "account number", "account no"],
    "bic": ["bank bic/swift", "bic/swift", "swift/bic", "bic", "swift"],
    "amount": ["amount due", "total due", "total amount", "amount"],
    "currency": ["currency"],
    "due_date": ["due date", "pay by", "payment deadline", "deadline"],
}
LABEL_LOOKUP = {lab: field for field, labs in LABELS.items() for lab in labs}

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules|checks)",
    r"(system|admin|developer|ai) (notice|override|message|prompt|instruction)",
    r"\b(note|message|notice) to (the )?(ai|assistant|agent|model)\b",
    r"\byou (are|must) now\b",
    r"\b(skip|bypass|disable|waive|override)\b[^.\n]{0,40}\b(check|verification|rules?|limits?|polic(y|ies)|security)\b",
    r"pre-?approved",
    r"\b(raise|increase|set|change|remove|lift)\b[^.\n]{0,30}\blimit",
    r"do not (tell|inform|alert|verify|notify)",
    r"(approve|execute|release|send) (this|the) (payment|transfer)[^.\n]{0,20}(immediately|now|without)",
]
CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}


def read_document(path: str) -> str:
    if path.lower().endswith(".pdf"):
        import pdfplumber  # pip install pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_amount(raw: str):
    """Return (Decimal|None, currency|None)."""
    s = raw.strip()
    cur = None
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in s:
            cur = code
            s = s.replace(sym, " ")
    m = re.search(r"\b([A-Z]{3})\b", s)
    if m:
        cur = m.group(1)
        s = s.replace(m.group(1), " ")
    m = re.search(r"\d[\d,]*(?:\.\d{1,2})?", s)
    if not m:
        return None, cur
    try:
        return Decimal(m.group(0).replace(",", "")), cur
    except InvalidOperation:
        return None, cur


def parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def detect_injection(text: str) -> list:
    hits = []
    for pat in INJECTION_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            snippet = m.group(0).strip()[:80]
            if snippet not in hits:
                hits.append(snippet)
    return hits


def extract(text: str, kind: str = "invoice", llm_fn=None) -> PaymentDetails:
    d = PaymentDetails(kind=kind, source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
    seen = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        field = LABEL_LOOKUP.get(label.strip().lower())
        value = value.strip()
        if not field or not value:
            continue
        if field in seen and seen[field] != value:
            d.inconsistencies.append(f"'{field}' appears twice with different values")
            continue
        seen.setdefault(field, value)

    d.institution = seen.get("institution")
    d.invoice_ref = seen.get("invoice_ref")
    d.beneficiary_name = seen.get("beneficiary_name")
    d.account = seen.get("account")
    d.bic = seen.get("bic")
    amt_cur = None
    if "amount" in seen:
        d.amount, amt_cur = parse_amount(seen["amount"])
    label_cur = seen["currency"].strip().upper() if "currency" in seen else None
    if amt_cur and label_cur and amt_cur != label_cur:
        d.inconsistencies.append(f"amount currency {amt_cur} conflicts with currency field {label_cur}")
    d.currency = amt_cur or label_cur
    if "due_date" in seen:
        d.due_date = parse_date(seen["due_date"])
        if d.due_date is None:
            d.inconsistencies.append("due date could not be parsed")

    d.injection_findings = detect_injection(text)

    if llm_fn is not None:  # optional AI assist, grounded
        try:
            suggestions = llm_fn(text) or {}
        except Exception as exc:  # never let the AI path break the deterministic path
            suggestions = {}
            d.inconsistencies.append(f"LLM assist failed: {type(exc).__name__}")
        norm = re.sub(r"\s+", "", text).upper()
        for f, v in suggestions.items():
            if f in ("institution", "invoice_ref", "beneficiary_name", "account", "bic") \
                    and getattr(d, f) is None and isinstance(v, str) and v:
                if re.sub(r"\s+", "", v).upper() in norm:   # grounding check
                    setattr(d, f, v)
                    d.llm_filled.append(f)
        if d.llm_filled:
            d.extraction_method = "rules+llm"

    for f in ("institution", "invoice_ref", "beneficiary_name", "account", "amount", "currency"):
        if getattr(d, f) in (None, ""):
            d.missing.append(f)
    return d
