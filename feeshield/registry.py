"""Small trusted reference registry (SYNTHETIC demo data). Only an administrative, out-of-band
verification step (add_verified) can add or change entries - never the agent or a document."""
from dataclasses import dataclass, field

from .models import PaymentDetails, mask_account, norm_account, norm_text

SEED = [
    # display, aliases, beneficiary, account, bic, currency
    ("Northfield University", ["Northfield Univ", "NFU"], "Northfield University Tuition Account",
     "GB00NFLD00000000457123", "NFLDGB2L", "GBP"),
    ("Lakeview Institute of Technology", ["LIT"], "Lakeview Institute of Technology Bursar",
     "US00LAKE00000000778812", "LAKEUS33", "USD"),
    ("Maple Ridge College", ["MRC"], "Maple Ridge College Fees",
     "CA00MAPL00000000334455", "MAPLCA2T", "CAD"),
]


@dataclass
class RegistryResult:
    status: str                 # VERIFIED | MISMATCH | NAME_MISMATCH | UNVERIFIED
    institution: str = ""
    diffs: list = field(default_factory=list)
    source: str = ""


class TrustedRegistry:
    def __init__(self, conn, clock, seed=True):
        self.conn, self.clock = conn, clock
        conn.execute("""CREATE TABLE IF NOT EXISTS institutions(
            id INTEGER PRIMARY KEY, display TEXT, aliases TEXT, beneficiary TEXT, account TEXT,
            bic TEXT, currency TEXT, source TEXT, verified_at TEXT)""")
        if seed and conn.execute("SELECT COUNT(*) c FROM institutions").fetchone()["c"] == 0:
            for disp, al, ben, acc, bic, cur in SEED:
                self.add_verified(disp, al, ben, acc, bic, cur,
                                  source="SYNTHETIC demo registry (not real verification)")

    def add_verified(self, display, aliases, beneficiary, account, bic, currency, source):
        self.conn.execute(
            "INSERT INTO institutions(display,aliases,beneficiary,account,bic,currency,source,verified_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (display, "|".join(aliases), beneficiary, norm_account(account), norm_account(bic),
             currency.upper(), source, self.clock.now().isoformat()))
        self.conn.commit()

    def _find(self, name):
        n = norm_text(name)
        for r in self.conn.execute("SELECT * FROM institutions"):
            names = [norm_text(r["display"])] + [norm_text(a) for a in r["aliases"].split("|") if a]
            if n and n in names:
                return r
        return None

    def check(self, d: PaymentDetails) -> RegistryResult:
        row = self._find(d.institution)
        acct = norm_account(d.account)
        if row is None:
            if acct:  # does this account belong to a *different* trusted institution?
                other = self.conn.execute("SELECT * FROM institutions WHERE account=?", (acct,)).fetchone()
                if other:
                    return RegistryResult("MISMATCH", other["display"], [{
                        "field": "account", "expected": f"not {other['display']}",
                        "observed": mask_account(acct), "severity": "critical"}], other["source"])
            return RegistryResult("UNVERIFIED", "", [], "")
        diffs = []
        if acct != row["account"]:
            diffs.append({"field": "account", "expected": mask_account(row["account"]),
                          "observed": mask_account(acct) or "(missing)", "severity": "critical"})
        if d.bic and norm_account(d.bic) != row["bic"]:
            diffs.append({"field": "bic", "expected": row["bic"], "observed": norm_account(d.bic),
                          "severity": "critical"})
        if d.beneficiary_name and norm_text(d.beneficiary_name) != norm_text(row["beneficiary"]):
            diffs.append({"field": "beneficiary_name", "expected": row["beneficiary"],
                          "observed": d.beneficiary_name, "severity": "material"})
        if d.currency and d.currency.upper() != row["currency"]:
            diffs.append({"field": "currency", "expected": row["currency"], "observed": d.currency,
                          "severity": "material"})
        crit = any(x["severity"] == "critical" for x in diffs)
        name_only = diffs and not crit and all(x["field"] in ("beneficiary_name", "currency") for x in diffs)
        status = "MISMATCH" if crit else ("NAME_MISMATCH" if name_only else "VERIFIED")
        return RegistryResult(status, row["display"], diffs, row["source"])
