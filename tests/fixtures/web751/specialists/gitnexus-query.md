---
name: gitnexus-query
pipeline_order: 5
triggers:
  pipeline_order: 5
  intent:
    must_any:
      - 'semantic quer'
      - 'call[- ]?graph'
      - '\bxrefs?\b'
      - 'cross[- ]?reference'
      - '\bcallers?\b of'
      - '\bwho calls\b'
      - '调用链'
      - '调用者'
      - '谁调用'
      - '\btrace[a-z]*\b[^.;]{0,40}\bfunctions?\b'
    exclude:
      - '\.net\b'
  features:
    language:
      any_of:
        - 'JavaScript'
        - 'TypeScript'
        - 'web'
---

# gitnexus-query (trigger-contract fixture — #751)

NOT an installed agent. This file pins the mechanical trigger block the
#760 web-re-worker wave must land inside its agent definition so
route_capability's specialist routing can select graph-RAG navigation for
web signature-tracing claims (issue #751 design D2). The registry/tooling
layer is carried by tools/_INDEX.yaml `gitnexus-query` (android + js
domains) — queries run over a lazily built gitnexus index.
