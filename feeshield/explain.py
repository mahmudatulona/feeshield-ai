"""Plain-language explanations built from the deterministic findings (templates, not an AI model)."""
HEAD = {
    "ALLOW": "ALLOW - every mandatory check passed. You can authorize this sandbox payment.",
    "HOLD": "HOLD - nothing was sent. Something needs verification or your review first.",
    "BLOCK": "BLOCK - nothing was sent. A mandatory security or authorization rule was violated.",
}


def explain(decision) -> str:
    lines = [HEAD[decision.outcome], ""]
    for f in decision.failed:
        lines.append(f"[{f.outcome}] {f.code}: {f.message}")
        for dct in f.evidence.get("diffs", []):
            lines.append(f"    - {dct['field']}: expected {dct['expected']} but saw {dct['observed']}")
        for s in f.evidence.get("snippets", []):
            lines.append(f"    - suspicious text ignored: \"{s}\"")
    if decision.passed:
        lines += ["", "Checks passed:"] + [f"  [ok] {f.code}: {f.message}" for f in decision.passed]
    return "\n".join(lines)
