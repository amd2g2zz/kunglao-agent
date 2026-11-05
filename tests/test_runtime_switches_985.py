# -*- coding: utf-8 -*-
"""Runtime-switch registry contract.

Four pinned properties:

  1. every keyed environment read under hooks/, scripts/ and devkit/
     either resolves through ``scripts/runtime_switches.py`` or is one of
     the three documented allowlist sites;
  2. supply/protection boolean switches declare a default of ON and
     learning boolean switches declare a default of OFF;
  3. an undeclared switch name (and an unparseable boolean value) fails
     closed instead of silently defaulting;
  4. the evaluation-arm declaration matrix and the dispatch context both
     carry the declared switch values, and Gate 10's SKIP-vs-fail
     behaviour is explicit.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
SCRIPTS = ROOT / "scripts"
DEVKIT = ROOT / "devkit"
MATRIX = ROOT / "docs" / "design" / "ws5-five-arms.yaml"

import runtime_switches as rs  # noqa: E402  # pytest.ini pythonpath = scripts

REGISTRY_MODULE = "scripts/runtime_switches.py"

#: the six switches an evaluation arm must declare explicitly (the
#: supply face plus the learning flags whose silence would otherwise
#: contaminate an ablation reading)
ARM_DECLARED = {
    "KUNGLAO_RECALL",
    "KUNGLAO_PREDICT_BEFORE_TRY",
    "KUNGLAO_META_RETRIEVAL",
    "KUNGLAO_META_VALUE_TABLE",
    "KUNGLAO_META_ATTRIBUTION",
    "KUNGLAO_META_PLAYBOOK",
}


# ------------------------------------------------ 1. the read scan


def _attr_chain(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _environ_import_names(tree: ast.AST) -> set[str]:
    """Names bound to the os.environ mapping (including renamed imports)."""
    names = {"environ"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name == "environ":
                    names.add(alias.asname or "environ")
    return names


def _is_env_snapshot(node: ast.AST, aliases: set[str],
                     env_names: set[str]) -> bool:
    """True for os.environ/environ, dict(...), .copy(), or a known alias."""
    if isinstance(node, ast.IfExp):
        return (_is_env_snapshot(node.body, aliases, env_names)
                or _is_env_snapshot(node.orelse, aliases, env_names))
    if isinstance(node, ast.Name):
        return node.id in aliases or node.id in env_names
    if isinstance(node, ast.Attribute):
        return _attr_chain(node) in ("os.environ", "environ")
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "dict" and node.args:
            return _is_env_snapshot(node.args[0], aliases, env_names)
        if isinstance(fn, ast.Attribute) and fn.attr == "copy":
            return (_attr_chain(fn.value) in ("os.environ", "environ")
                    or _is_env_snapshot(fn.value, aliases, env_names))
    return False


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_target_names(element))
        return names
    return []


def _scope_nodes(stmts):
    """Nodes belonging to one scope; nested function/class bodies excluded."""
    stack = list(stmts)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _params_of(fn: ast.AST) -> set[str]:
    args = fn.args  # type: ignore[attr-defined]
    names = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _snapshot_names(targets, value: ast.AST, aliases: set[str],
                    env_names: set[str]) -> list[str]:
    """Names bound to an environment snapshot by one assignment."""
    if len(targets) == 1 \
            and isinstance(targets[0], (ast.Tuple, ast.List)) \
            and isinstance(value, (ast.Tuple, ast.List)) \
            and len(targets[0].elts) == len(value.elts):
        names: list[str] = []
        for target, element in zip(targets[0].elts, value.elts):
            if _is_env_snapshot(element, aliases, env_names):
                names.extend(_target_names(target))
        return names
    if not _is_env_snapshot(value, aliases, env_names):
        return []
    names = []
    for target in targets:
        names.extend(_target_names(target))
    return names


def _scope_aliases(stmts, incoming: set[str],
                   params: set[str] | None = None,
                   env_names: set[str] | None = None) -> set[str]:
    """Environment-snapshot aliases visible in one lexical scope."""
    env_names = env_names or {"environ"}
    nodes = list(_scope_nodes(stmts))
    shadow = set(params or ()) | {
        node.id for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    aliases = {name for name in incoming if name not in shadow}
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.NamedExpr):
                targets, value = [node.target], node.value
            else:
                continue
            for name in _snapshot_names(targets, value, aliases, env_names):
                if name not in aliases:
                    aliases.add(name)
                    changed = True
    return aliases


def _constant_strings(tree: ast.AST) -> dict[str, str]:
    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) \
                and isinstance(node.target, ast.Name):
            consts[node.target.id] = node.value.value
    return consts


def _key_literal(node: ast.AST | None, consts: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def _read_key(node: ast.AST, aliases: set[str],
              env_names: set[str]) -> tuple[bool, ast.AST | None]:
    """(is_keyed_read, key_node) for one AST node in an alias scope."""
    if isinstance(node, ast.Call):
        fn = node.func
        key_node = node.args[0] if getattr(node, "args", None) else None
        if isinstance(fn, ast.Attribute) and fn.attr == "get":
            if _is_env_snapshot(fn.value, aliases, env_names):
                return True, key_node
        elif isinstance(fn, ast.Name) and fn.id == "getenv":
            return True, key_node
        elif isinstance(fn, ast.Attribute) and fn.attr == "getenv" \
                and _attr_chain(fn.value) == "os":
            return True, key_node
        return False, None
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        if _is_env_snapshot(node.value, aliases, env_names):
            return True, node.slice
    return False, None


def _keyed_reads(path: Path) -> list[tuple[int, str | None]]:
    """Keyed environment reads in one module: (line, literal-or-None).

    Tracks direct reads, `getenv`, subscript loads, and keyed reads through
    environment snapshots (`dict(os.environ)`, `os.environ.copy()`, and
    transitive aliases) with lexical-scope awareness so a parameter or
    local that merely shares an alias's name is not misread.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    consts = _constant_strings(tree)
    env_names = _environ_import_names(tree)
    out: list[tuple[int, str | None]] = []

    def record(node: ast.AST, key_node: ast.AST | None) -> None:
        out.append((getattr(node, "lineno", 0), _key_literal(key_node, consts)))

    def scan(stmts, incoming: set[str],
             params: set[str] | None = None) -> None:
        aliases = _scope_aliases(stmts, incoming, params, env_names)
        for node in _scope_nodes(stmts):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scan(node.body, aliases, _params_of(node))
                continue
            if isinstance(node, ast.ClassDef):
                scan(node.body, aliases)
                continue
            if isinstance(node, ast.Lambda):
                scan([node.body], aliases, _params_of(node))
                continue
            hit, key_node = _read_key(node, aliases, env_names)
            if hit:
                record(node, key_node)

    scan(tree.body, set())
    return out


def _raw_reads() -> list[tuple[str, int, str | None]]:
    found: list[tuple[str, int, str | None]] = []
    for base in (HOOKS, SCRIPTS, DEVKIT):
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel == REGISTRY_MODULE:
                continue
            for line, literal in _keyed_reads(path):
                found.append((rel, line, literal))
    return found


def test_scanner_catches_environment_snapshot_aliases(tmp_path):
    """Regression pin for the alias blind spot: a `dict(os.environ)` or
    `os.environ.copy()` view read through `.get` / subscript must be
    visible to the scanner (it would otherwise wave raw reads through)."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\n"
        "from os import environ as renv\n"
        "base = dict(os.environ) if flag else dict(other)\n"
        "base.get('TF_TOOLBOX')\n"
        "base['PATH']\n"
        "copy = os.environ.copy()\n"
        "copy.get('HOME')\n"
        "chained = dict(base)\n"
        "chained.get('TF_DYNAMIC')\n"
        "os.environ.copy().get('TF_CHAIN')\n"
        "dict(os.environ)['TF_SUB']\n"
        "renv.copy().get('TF_RENV')\n"
        "(walrus := dict(os.environ))\n"
        "walrus.get('TF_WALRUS')\n"
        "t1, t2 = dict(os.environ), None\n"
        "t1.get('TF_TUPLE')\n"
        "class C:\n"
        "    e = dict(os.environ)\n"
        "    x = e.get('TF_CLASS')\n"
        "fx = lambda: dict(os.environ).get('TF_LAMBDA')\n"
        "def plain(env):\n"
        "    return env.get('NOT_ENV')\n",
        encoding="utf-8")
    literals = {literal for _line, literal in _keyed_reads(sample)}
    assert {"TF_TOOLBOX", "PATH", "HOME", "TF_DYNAMIC", "TF_CHAIN",
            "TF_SUB", "TF_RENV", "TF_WALRUS", "TF_TUPLE", "TF_CLASS",
            "TF_LAMBDA"} <= literals
    assert "NOT_ENV" not in literals, (
        "a parameter mapping is not an environment snapshot")


def test_every_env_read_resolves_through_the_registry():
    offenders: list[str] = []
    for rel, line, literal in _raw_reads():
        if literal is None:
            offenders.append(f"{rel}:{line}: dynamic switch name")
            continue
        sites = rs.ALLOWLIST_SITES.get(literal, frozenset())
        if rel in sites:
            continue
        if literal not in rs.SWITCHES:
            offenders.append(f"{rel}:{line}: undeclared switch {literal}")
        else:
            offenders.append(
                f"{rel}:{line}: raw read of declared switch {literal} "
                "(route it through runtime_switches)")
    assert not offenders, "\n".join(offenders)


def test_allowlist_is_the_documented_three_sites():
    assert set(rs.ALLOWLIST_SITES) == {
        "KUNGLAO_PROBE_TIMEOUT_FLOOR",
        "KUNGLAO_E2E_MAX_PARALLEL",
        "GITHUB_SHA",
    }
    for name, sites in rs.ALLOWLIST_SITES.items():
        assert name in rs.SWITCHES, name
        assert rs.SWITCHES[name].allowlist_reason, name
        assert sites, name
        for rel in sites:
            assert (ROOT / rel).is_file(), f"{name}: missing allowlist site {rel}"


# ------------------------------------------------ 2. the registry shape


def test_registry_names_are_unique():
    names = [row[0] for row in rs._ENTRIES]
    assert len(names) == len(set(names)), "duplicate switch declaration"
    assert set(names) == set(rs.SWITCHES)


def test_registry_entries_are_complete():
    for name, spec in rs.SWITCHES.items():
        assert name.isupper(), name
        assert spec.type in rs.TYPES, (name, spec.type)
        assert spec.direction in rs.DIRECTIONS, (name, spec.direction)
        assert spec.declared in rs.DECLARED_FACES, (name, spec.declared)
        assert spec.owner, name
        assert (ROOT / spec.owner).is_file(), (name, spec.owner)
        assert spec.doc.strip(), name


def test_polarity_supply_protection_on_learning_off():
    supply = {n for n, s in rs.SWITCHES.items()
              if s.type == "bool" and s.direction == "supply"}
    protection = {n for n, s in rs.SWITCHES.items()
                  if s.type == "bool" and s.direction == "protection"}
    learning = {n for n, s in rs.SWITCHES.items()
                if s.type == "bool" and s.direction == "learning"}
    assert "KUNGLAO_RECALL" in supply
    assert {
        "KUNGLAO_META_RETRIEVAL", "KUNGLAO_META_VALUE_TABLE",
        "KUNGLAO_META_ATTRIBUTION", "KUNGLAO_META_PLAYBOOK",
        "KUNGLAO_PREDICT_BEFORE_TRY", "KUNGLAO_DIRECTION",
        "KUNGLAO_EVAL_SETTLE", "KUNGLAO_PLAYBOOK",
    } <= learning
    for name in supply | protection:
        assert rs.SWITCHES[name].default is True, (
            f"{name}: supply/protection silence must default ON")
    for name in learning:
        assert rs.SWITCHES[name].default is False, (
            f"{name}: learning silence must default OFF")


def test_unknown_switch_fails_closed():
    for read in (rs.get, rs.raw, rs.spec, rs.get_bool, rs.get_int,
                 rs.get_float, rs.get_str):
        with pytest.raises(ValueError, match="unknown runtime switch"):
            read("KUNGLAO_NOT_A_DECLARED_SWITCH")


def test_unparseable_bool_value_fails_closed(monkeypatch):
    monkeypatch.setenv("KUNGLAO_META_RETRIEVAL", "sometimes")
    with pytest.raises(ValueError, match="KUNGLAO_META_RETRIEVAL"):
        rs.get_bool("KUNGLAO_META_RETRIEVAL")


def test_typed_helpers_and_defaults(monkeypatch):
    monkeypatch.delenv("KUNGLAO_E2E_ACT_TIMEOUT_S", raising=False)
    assert rs.get_int("KUNGLAO_E2E_ACT_TIMEOUT_S") == 1800
    monkeypatch.setenv("KUNGLAO_E2E_ACT_TIMEOUT_S", "2400")
    assert rs.get_int("KUNGLAO_E2E_ACT_TIMEOUT_S") == 2400
    monkeypatch.setenv("KUNGLAO_E2E_ACT_TIMEOUT_S", "garbage")
    assert rs.get_int("KUNGLAO_E2E_ACT_TIMEOUT_S") == 1800


# ------------------------------------------------ 3. the reader defaults


def test_recall_supply_defaults_on(tmp_path, monkeypatch):
    """The supply face is ON unless an arm declares it off."""
    monkeypatch.delenv("KUNGLAO_RECALL", raising=False)
    import recall_inject

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    payload = {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": (
            '{"kunglao_dispatch": {"version": 1, "claim": "C-101", '
            '"tier": 3, "tools": ["frida"]}}\nobserve the dynamic '
            "behavior in the VM with frida injection")},
    }
    rc, stderr, ctx = recall_inject.evaluate(
        payload, recall_runner=lambda q: (0, "re-library/a.md | a | b | c"))
    assert rc == 0 and stderr == "" and ctx is not None


def test_recall_arm_declaration_still_ablates(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_RECALL", "0")
    import recall_inject

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    payload = {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": (
            '{"kunglao_dispatch": {"version": 1, "claim": "C-101", '
            '"tier": 3, "tools": ["frida"]}}\nobserve the dynamic '
            "behavior in the VM with frida injection")},
    }
    assert recall_inject.evaluate(
        payload, recall_runner=lambda q: (0, "re-library/a.md | a | b | c")
    ) == (0, "", None)


def test_learning_switches_default_off(monkeypatch):
    for name in ARM_DECLARED | {
            "KUNGLAO_DIRECTION", "KUNGLAO_EVAL_SETTLE", "KUNGLAO_PLAYBOOK"}:
        monkeypatch.delenv(name, raising=False)
    from rlvr import attribution as attr
    from rlvr import meta_policy as mp
    from rlvr import playbook as pb

    k = mp.knobs()
    assert k["retrieval"] is False
    assert k["value_table"] is False
    assert k["attribution"] is False
    assert k["playbook"] is False
    assert attr.knob_on() is False
    assert pb.knob_on() is False


def test_learning_switches_declared_on_are_read(monkeypatch):
    from rlvr import attribution as attr
    from rlvr import meta_policy as mp
    from rlvr import playbook as pb

    for name in ("KUNGLAO_META_RETRIEVAL", "KUNGLAO_META_VALUE_TABLE",
                 "KUNGLAO_META_ATTRIBUTION", "KUNGLAO_META_PLAYBOOK"):
        monkeypatch.setenv(name, "1")
    k = mp.knobs()
    assert k["retrieval"] is True and k["value_table"] is True
    assert k["attribution"] is True and k["playbook"] is True
    assert attr.knob_on() is True and pb.knob_on() is True


# ------------------------------------------------ 4. declaration surfaces


def test_arm_matrix_declares_recall_and_meta_switches():
    doc = yaml.safe_load(MATRIX.read_text(encoding="utf-8"))
    arms = doc["arms"]
    for arm in arms:
        env = arm.get("env") or {}
        missing = ARM_DECLARED - set(env)
        assert not missing, f"arm {arm.get('id')} does not declare {missing}"
    declared = {name for name, spec in rs.SWITCHES.items()
                if spec.declared == "arm"}
    assert declared == ARM_DECLARED


def test_arm_matrix_values_match_declared_defaults():
    doc = yaml.safe_load(MATRIX.read_text(encoding="utf-8"))
    for arm in doc["arms"]:
        env = arm.get("env") or {}
        recall = env["KUNGLAO_RECALL"]
        meta = {name: env[name] for name in (
            "KUNGLAO_META_RETRIEVAL", "KUNGLAO_META_VALUE_TABLE",
            "KUNGLAO_META_ATTRIBUTION", "KUNGLAO_META_PLAYBOOK")}
        if arm["id"] == "kunglao-warm-no-l1":
            assert recall == "0", "the L1 ablation arm must declare recall off"
        elif arm["runner_face"] == "loop":
            assert recall == "1"
        else:
            assert recall == "0"
        if arm["runner_face"] == "loop":
            assert set(meta.values()) == {"1"}, arm["id"]
        else:
            assert set(meta.values()) == {"0"}, arm["id"]


def test_matrix_stripped_env_covers_the_declared_arms():
    from eval_matrix_runner import STRIPPED_ENV

    stripped = set(STRIPPED_ENV)
    assert ARM_DECLARED <= stripped
    assert {"KUNGLAO_EXPANSION", "KUNGLAO_SCHEDULER",
            "KUNGLAO_DIRECTION", "KUNGLAO_EVAL_SETTLE",
            "KUNGLAO_PLAYBOOK"} <= stripped


def test_dispatch_context_carries_declared_values(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_RECALL", raising=False)
    monkeypatch.delenv("KUNGLAO_META_ATTRIBUTION", raising=False)
    import dispatch_context as dc

    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
    ctx = dc.build_dispatch_context(
        ws=ws, claim_id="C-001", tier=1, tools=[], agent_name="worker")
    block = ctx["runtime_switches"]
    assert block["schema"] == "runtime-switches/1"
    assert block["declared_defaults"]["KUNGLAO_RECALL"] is True
    assert block["declared_defaults"]["KUNGLAO_META_ATTRIBUTION"] is False
    assert block["values"]["KUNGLAO_RECALL"] is True
    assert block["values"]["KUNGLAO_META_ATTRIBUTION"] is False
    assert block["sources"]["KUNGLAO_RECALL"] == "default"
    assert json.dumps(block)  # deterministic, serialisable context


def test_dispatch_context_reports_env_source(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_META_ATTRIBUTION", "1")
    import dispatch_context as dc

    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
    block = dc.build_dispatch_context(
        ws=ws, claim_id="C-001", tier=1, tools=[], agent_name="worker"
    )["runtime_switches"]
    assert block["values"]["KUNGLAO_META_ATTRIBUTION"] is True
    assert block["sources"]["KUNGLAO_META_ATTRIBUTION"] == "env"


# ------------------------------------------------ 5. Gate 10


def _load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "quality_gates_985", DEVKIT / "quality_gates.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate10_unset_skips_loudly(monkeypatch, capsys):
    monkeypatch.delenv("KUNGLAO_LIVENESS_WS", raising=False)
    qg = _load_gate_module()
    assert qg._gate10_liveness() is True
    out = capsys.readouterr().out
    assert "SKIP: KUNGLAO_LIVENESS_WS not set" in out


def test_gate10_set_but_invalid_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_LIVENESS_WS", str(tmp_path / "no-such-ws"))
    qg = _load_gate_module()
    assert qg._gate10_liveness() is False


def test_gate10_switch_registered():
    assert "KUNGLAO_LIVENESS_WS" in rs.SWITCHES
    spec = rs.SWITCHES["KUNGLAO_LIVENESS_WS"]
    assert spec.direction == "protection"
    assert spec.default == ""
    assert "SKIP" in spec.doc


# ------------------------------------------------ 6. one timeout parse


def test_act_timeout_has_one_parse_face(monkeypatch):
    monkeypatch.setenv("KUNGLAO_E2E_ACT_TIMEOUT_S", "2400")
    assert rs.get_int("KUNGLAO_E2E_ACT_TIMEOUT_S") == 2400
    from e2e import llm_faces
    from rlvr import meta_arms

    for rel in ("scripts/e2e/llm_faces.py", "scripts/rlvr/meta_arms.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "runtime_switches" in src, rel
        assert "os.environ" not in src, rel
    assert llm_faces._act_timeout_s() == 2400
    assert meta_arms.act_timeout_s() == 2400
    assert meta_arms.act_timeout_s() == llm_faces._act_timeout_s()
