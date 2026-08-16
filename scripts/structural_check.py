#!/usr/bin/env python3
"""structural_check.py -- CI structural integrity checks (#141)."""
from __future__ import annotations
import re, sys
from pathlib import Path

def check_re_library_orphans(root):
    re_lib = root / 'references' / 're-library'
    if not re_lib.exists(): return []
    refs_text = ''
    for p in root.glob('references/*.md'):
        refs_text += p.read_text(encoding='utf-8')
    skill = (root / 'SKILL.md').read_text(encoding='utf-8') if (root / 'SKILL.md').exists() else ''
    index = (root / 'references' / 'INDEX.md').read_text(encoding='utf-8') if (root / 'references' / 'INDEX.md').exists() else ''
    all_refs = refs_text + skill + index
    orphans = []
    for p in sorted(re_lib.glob('*.md')):
        if p.name not in all_refs:
            orphans.append(str(p.relative_to(root)))
    return orphans

def check_index_drift(root):
    facts_dir = root / 'facts'
    index = facts_dir / '_INDEX.md'
    if not facts_dir.exists() or not index.exists(): return []
    index_text = index.read_text(encoding='utf-8')
    actual = {p.stem for p in facts_dir.glob('F*.md')}
    indexed = set(re.findall(r'F\d+', index_text))
    missing_in_index = sorted(actual - indexed)
    missing_on_disk = sorted(indexed - actual)
    issues = []
    for m in missing_in_index: issues.append(f'MISSING_IN_INDEX: {m}')
    for m in missing_on_disk: issues.append(f'MISSING_ON_DISK: {m}')
    return issues

def check_reference_links(root):
    refs_dir = root / 'references'
    if not refs_dir.exists(): return []
    issues = []
    for p in sorted(refs_dir.glob('**/*.md')):
        text = p.read_text(encoding='utf-8')
        for m in re.finditer(r'\]\(([^)]+\.md)\)', text):
            target = m.group(1)
            if target.startswith('http'): continue
            resolved = (p.parent / target).resolve()
            if not resolved.exists():
                issues.append(f'BROKEN_LINK: {p.relative_to(root)} -> {target}')
    return issues

def check_references_index_drift(root):
    refs_index = root / 'references' / '_INDEX.yaml'
    if not refs_index.exists():
        return ['ERROR MISSING_REFERENCES_INDEX: references/_INDEX.yaml']
    import hashlib
    try:
        import yaml
        data = yaml.safe_load(refs_index.read_text(encoding='utf-8')) or {}
    except Exception:
        return ['ERROR REFERENCES_INDEX_UNREADABLE: references/_INDEX.yaml']
    files = data.get('files') or {}
    issues = []
    for rel, expect in files.items():
        p = root / rel
        if not p.exists():
            issues.append(f'ERROR INDEX_DRIFT: {rel} missing on disk')
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expect:
            issues.append(f'ERROR INDEX_DRIFT: {rel} (digest mismatch)')
    return issues

def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    errors = []
    warnings = []
    orphans = check_re_library_orphans(root)
    for o in orphans: warnings.append(f'WARN ORPHAN: {o}')
    drift = check_index_drift(root)
    for d in drift: errors.append(d)
    broken = check_reference_links(root)
    for b in broken: errors.append(b)
    ref_drift = check_references_index_drift(root)
    errors = errors + ref_drift
    for w in warnings: print(w)
    for e in errors:
        print(e if e.startswith('ERROR ') else 'ERROR ' + e)
    if errors:
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
