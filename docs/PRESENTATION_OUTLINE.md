# 10-minute presentation outline
1. (0:00-1:00) Problem: students send tuition across borders; three failure modes: wrong recipient, hidden cost, cash crunch.
2. (1:00-2:00) Insight: they are one decision, not three tools. Sample: $1,500 tuition, $2,000 balance, $400 rent.
3. (2:00-3:30) Architecture slide (docs/ARCHITECTURE.md): untrusted docs -> facts -> deterministic policy -> gateway.
4. (3:30-8:00) Live demo (demo script): invoice -> intent fingerprint -> 3 options -> HOLD vs ALLOW -> changed beneficiary BLOCK -> alternative -> authorized sandbox execution -> audit log.
5. (8:00-9:00) Evidence: 30 tests (docs/TEST_RESULTS.md), execution log (evidence/), honest limitations.
6. (9:00-10:00) Innovation claim (state only what we can support), roadmap, ask.
Note: competitor comparison slide must be built from verified research (not yet done).
