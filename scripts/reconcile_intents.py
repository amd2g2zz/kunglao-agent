"""reconcile_intents — WAL cold-restart reconciliation (DESIGN §14).

On cold-restart, the orchestrator calls reconcile() to detect crash-induced state drift:
  - in_flight intent → worker crashed or completed-unmarked → re-dispatch (idempotent
    via fact_id, so safe whether the worker wrote the fact or not)
  - fact file (content-hash id, len 17) with NO intent at all → orphan → blockers/

Pre-existing ordinal facts (F001, len 4) predate kunglao-agent and are exempt.
"""
from __future__ import annotations

import sys
from pathlib import Path

# len of a content-hash fact_id: 'F' + 16 hex = 17 (see content_hash.HEX_LEN)
CONTENT_HASH_LEN = 17


def read_intents(path: Path) -> list[dict]:
    """Read the [intents] segment of analysis_state.txt → list of intent dicts."""
    if not path.exists():
        return []
    in_seg = False
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if s == '[intents]':
            in_seg = True
            continue
        if s == '[/intents]':
            break
        if in_seg and ' | ' in line:
            entry = {}
            for part in line.split(' | '):
                k, _, v = part.partition('=')
                entry[k.strip()] = v.strip()
            out.append(entry)
    return out


def reconcile(state_path: Path, facts_dir: Path | None) -> list[dict]:
    """Return a list of reconciliation issues.

    issue kinds:
      {'kind': 're-dispatch', 'intent_id', 'claim_id', 'fact_id'}
      {'kind': 'orphan', 'fact_id'}
    """
    issues: list[dict] = []
    intents = read_intents(state_path)
    all_fact_ids = {i.get('fact_id', '') for i in intents if i.get('fact_id')}

    for i in intents:
        if i.get('status') == 'in_flight':
            issues.append({
                'kind': 're-dispatch',
                'intent_id': i.get('intent_id', ''),
                'claim_id': i.get('claim_id', ''),
                'fact_id': i.get('fact_id', ''),
            })

    if facts_dir and facts_dir.exists():
        for f in sorted(facts_dir.glob('F*.md')):
            fid = f.stem
            if len(fid) == CONTENT_HASH_LEN and fid not in all_fact_ids:
                issues.append({'kind': 'orphan', 'fact_id': fid})

    return issues


def main(argv: list[str]) -> int:
    """CLI: python reconcile_intents.py <analysis_state.txt> [<facts_dir>]

    Prints one issue per line: '<kind> <fact_id> [<claim_id>]'.
    """
    if len(argv) < 2:
        print('Usage: reconcile_intents.py <analysis_state.txt> [<facts_dir>]', file=sys.stderr)
        return 2
    state = Path(argv[1])
    facts = Path(argv[2]) if len(argv) >= 3 else (state.parent / 'facts')
    for issue in reconcile(state, facts):
        if issue['kind'] == 're-dispatch':
            print(f"re-dispatch {issue['fact_id']} claim={issue['claim_id']}")
        else:
            print(f"orphan {issue['fact_id']}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
