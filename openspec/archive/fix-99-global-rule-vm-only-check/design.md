## Design

### Approach

Mechanical regex/keyword-based parser. No LLM. The script:

1. **Parses SKILL.md "Hard prohibitions" section**: Extracts numbered items (1-5) from the `## Hard prohibitions` heading until the next `##` heading. For each item, stores:
   - Item number
   - Title keyword (bold text before the em-dash/description)
   - Key concepts: a set of stemmed/normalized words from the item body
   - Special markers: for VM-ONLY items, extracts HOST_FORBIDDEN_TOOLS list from inline code

2. **Parses global rules section 7**: Extracts numbered items from `## 7. 硬禁止` section. Same extraction.

3. **Subset check**: For each global rule item, checks if a SKILL item "covers" it. Coverage = overlap ratio of key concepts above threshold (0.3), OR exact title match, OR the global rule's title keywords are all found in some SKILL item's body.

4. **Reports**: Missing items printed with the global rule item number + text. Exit code 0 = all covered, 1 = gaps.

### Subtlety

The global rule #3 ("有 OPEN claim 时不 declare done") maps to SKILL #3 ("User feedback = dual-layer skepticism") only loosely. The subset check must use fuzzy keyword matching (concept overlap), not strict 1:1 numbering. The script identifies items by their semantic content, not by index.

### VM-ONLY detection

The script recognizes VM-ONLY by detecting any of these markers in a SKILL prohibition:
- "VM-ONLY" or "VM-resident" or "VM_only"
- Any of the HOST_FORBIDDEN_TOOLS names (`mcp__x64dbg__start_session`, etc.)
- "host machine" + "forbidden" in the same item

The global rule is considered to "cover" VM-ONLY if it contains at least 2 of these markers.
