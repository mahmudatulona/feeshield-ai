"""Cross-border cost intelligence. All money math uses Decimal.
EVERY rate and fee below is ILLUSTRATIVE SAMPLE DATA - not a live quote from any provider."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

D = Decimal
DATA_LABEL = "ILLUSTRATIVE SAMPLE DATA (not a live quote)"


def q2(x: Decimal) -> Decimal:
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    flat_fee: Decimal            # in source currency
    pct_fee: Decimal             # percent of converted amount
    fx_markup_pct: Decimal       # percent below mid-market rate
    intermediary_fee_dest: Decimal  # deducted from recipient in destination currency
    delivery: str


SCENARIOS = [
    Scenario("bank_wire", "Traditional bank wire (sample)", D("25.00"), D("0"), D("2.5"), D("10.00"), "2-4 business days"),
    Scenario("fintech_a", "Fintech transfer A (sample)", D("3.50"), D("0.45"), D("0.5"), D("0"), "1 business day"),
    Scenario("card_b", "Card-funded payment B (sample)", D("0"), D("1.90"), D("1.0"), D("0"), "same day"),
]
SCENARIO_BY_ID = {s.id: s for s in SCENARIOS}


class RateTable:
    """Mid-market rates, units of destination currency per 1 unit of source. Sample data."""

    def __init__(self, rates=None, as_of="2026-10-18 (sample)"):
        self.rates = dict(rates or {("USD", "GBP"): D("0.7700"), ("USD", "CAD"): D("1.3800")})
        self.as_of = as_of

    def get(self, src: str, dst: str) -> Decimal:
        if src == dst:
            return D("1")
        if (src, dst) not in self.rates:
            raise KeyError(f"no sample rate for {src}->{dst}")
        return self.rates[(src, dst)]

    def set(self, src, dst, rate):
        self.rates[(src, dst)] = D(str(rate))


@dataclass
class Quote:
    scenario_id: str
    scenario_name: str
    src_currency: str
    dst_currency: str
    total_src: Decimal
    fee_src: Decimal
    fx_cost_src: Decimal
    mid_rate: Decimal
    effective_rate: Decimal
    target_net_dest: Decimal
    intermediary_fee_dest: Decimal
    delivery: str
    cost_pct: Decimal
    rate_as_of: str
    data_label: str = DATA_LABEL


def _eff_rate(sc, mid, same):
    return D("1") if same else mid * (D("1") - sc.fx_markup_pct / D("100"))


def quote(sc: Scenario, target_dest: Decimal, src: str, dst: str, mid: Decimal, as_of="") -> Quote:
    same = src == dst
    eff = _eff_rate(sc, mid, same)
    interm = D("0") if same else sc.intermediary_fee_dest
    converted = (target_dest + interm) / eff
    fee = sc.flat_fee + converted * sc.pct_fee / D("100")
    total = q2(converted + fee)
    mid_value = target_dest / mid
    over = total - mid_value
    return Quote(sc.id, sc.name, src, dst, total, q2(fee), q2(converted - mid_value), mid, eff,
                 target_dest, interm, sc.delivery, (over / mid_value * D("100")).quantize(D("0.01")), as_of)


def net_received_for_budget(sc: Scenario, budget_src: Decimal, src: str, dst: str, mid: Decimal) -> Decimal:
    """If the student sends a fixed amount, how much does the recipient actually receive?"""
    same = src == dst
    eff = _eff_rate(sc, mid, same)
    interm = D("0") if same else sc.intermediary_fee_dest
    after_fee = (budget_src - sc.flat_fee) / (D("1") + sc.pct_fee / D("100"))
    return max(D("0"), q2(after_fee * eff - interm))
