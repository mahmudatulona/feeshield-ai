"""Policy limits. Frozen on purpose: neither the AI model nor document text can change them at runtime.
Limits are only changed by a human editing this file and restarting."""
import hashlib
import json
from dataclasses import dataclass, asdict
from decimal import Decimal


@dataclass(frozen=True)
class PolicyLimits:
    account_currency: str = "USD"
    per_transaction_limit: Decimal = Decimal("2000.00")  # in account currency
    daily_limit: Decimal = Decimal("3000.00")
    min_cash_buffer: Decimal = Decimal("50.00")          # must remain after payment + essentials
    fee_hold_pct: Decimal = Decimal("3.00")              # total cost over mid-market value
    fee_block_pct: Decimal = Decimal("6.00")
    rate_move_hold_pct: Decimal = Decimal("1.00")
    authorization_ttl_seconds: int = 300
    expense_horizon_days: int = 30

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:16]
