# Architecture (editable Mermaid source - paste into mermaid.live to render/export)
```mermaid
flowchart LR
  U[Student UI / Streamlit] --> A[Agent orchestrator]
  D[Invoice / instruction\nUNTRUSTED DATA] --> X[Extractor\nrules + optional grounded LLM assist]
  X --> A
  A --> R[(Trusted registry\nSQLite)]
  A --> C[Cost engine\nDecimal math, sample rates]
  A --> F[Cash-flow analysis]
  A -->|facts only| P[Deterministic Policy Engine\nALLOW / HOLD / BLOCK]
  P --> E[Explanation]
  U -->|typed confirmation| T[Authorization service\nsingle-use, expiring, hash-bound]
  A -->|request execute| G[Execution Gateway]
  G -->|re-runs policy itself| P
  G --> T
  G --> B[(Sandbox bank)]
  A --> L[(Hash-chained audit log\nmasked accounts)]
  G --> L
  P --> L
```
Trust boundary: everything left of the Policy Engine may be influenced by documents or an AI model; the Policy Engine, Authorization service, Gateway and Sandbox bank are plain deterministic code and never read model output as authority.
