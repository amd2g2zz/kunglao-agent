#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/opaque-pred.py — z3 opaque-predicate check + MBA simplifier (issue #306).

Fresh recursive-descent parser for the C expression subset Ghidra emits
(constants, hex literals, variables, unary ``~ - !``, binary
``+ - * / % ^ & | << >>``, comparisons, ``&& ||``, parentheses), translated to
z3 bit-vectors with 32-bit wrap-around semantics.

Why 32-bit bit-vectors (not unbounded integers): decompiled x86/x64 code
arithmetic wraps at the register width, and mixed boolean-arithmetic (MBA)
identities hold *modulo 2^n* — e.g. ``(x+1)*(x+1) == x*x+2*x+1`` is only a
valid identity with wrap-around semantics.  Modelling with mathematical
integers would both miss real opaque predicates (false negatives) and accept
identities that do not hold at 32 bits (false positives).  This mirrors the
32-bit workaround d810's z3 layer uses for the same reason (issue #306 design
comment #2 — technique only, fresh implementation).

Two modes:
  --expr "EXPR"          opaque-predicate check: two solver passes
                         (EXPR-unsat => always_true, !EXPR-unsat =>
                         always_false) with a 5s timeout each; else unknown.
  --simplify "a -> b"    MBA equivalence: prove a != b unsat; when proven,
                         emit b as the rewrite suggestion.

z3-solver is OPTIONAL: the module imports with a guarded try/except (--help
works without it); a check run without z3 exits 2 with install guidance.

Usage:
  opaque-pred --expr "x >= 0 || x < 0"
  opaque-pred --expr "(x+1)*(x+1) == x*x+2*x+1" --json
  opaque-pred --simplify "x*(x-1)&1 -> 0" --reproduce
  opaque-pred --expr "x > 5" --width 64

Exit codes: 0 = decided (always_true / always_false, or proven equivalent),
1 = unknown / not proven (input parsed, solver says neither), 2 = error
(parse error / z3 missing / bad usage).
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Union

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))


try:
    import z3  # optional dependency (degrade path: z3 = None -> exit 2)
except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
    z3 = None

EXIT_DECIDED = 0
EXIT_UNKNOWN = 1
EXIT_ERROR = 2

DEFAULT_WIDTH = 32
TIMEOUT_MS = 5000


# ---------------------------------------------------------------------------
# C expression AST (fresh recursive-descent implementation)
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """The expression is not in the supported C subset."""


@dataclass(frozen=True)
class Const:
    value: int


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: "Node"


@dataclass(frozen=True)
class Binary:
    op: str
    left: "Node"
    right: "Node"


Node = Union[Const, Var, Unary, Binary]

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (0[xX][0-9a-fA-F]+)        # hex literal
      | (\d+)                       # decimal literal
      | (<<|>>|<=|>=|==|!=|&&|\|\|) # two-char operators
      | ([A-Za-z_]\w*)              # identifier
      | (.)                         # single-char operator / paren
    )
    """,
    re.VERBOSE,
)

# C precedence, loose -> tight (multiplicative binds tighter than additive,
# shift sits between additive and relational, as in C).
_PRECEDENCE: dict[str, int] = {
    "||": 1, "&&": 2,
    "|": 3, "^": 4, "&": 5,
    "==": 6, "!=": 6,
    "<": 7, ">": 7, "<=": 7, ">=": 7,
    "<<": 8, ">>": 8,
    "+": 9, "-": 9,
    "*": 10, "/": 10, "%": 10,
}


def _tokenize(expr: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if m is None:
            raise ParseError(f"unexpected character {expr[pos]!r} at "
                             f"position {pos}")
        tokens.append(m.group(1) or m.group(2) or m.group(3) or m.group(4)
                      or m.group(5))
        pos = m.end()
    return tokens


class _Parser:
    """Precedence-climbing parser over the token list."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.prev: str | None = None

    def parse(self) -> Node:
        node = self._expr(0)
        if self.pos < len(self.tokens):
            raise ParseError(f"unexpected token {self.tokens[self.pos]!r} at "
                             f"position {self.pos}")
        return node

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _advance(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        self.prev = tok
        return tok

    def _expr(self, min_prec: int) -> Node:
        left = self._unary()
        while True:
            op = self._peek()
            if op is None or op not in _PRECEDENCE:
                break
            prec = _PRECEDENCE[op]
            if prec < min_prec:
                break
            self._advance()
            right = self._expr(prec + 1)
            left = Binary(op, left, right)
        return left

    def _unary(self) -> Node:
        tok = self._peek()
        if tok in ("~", "!"):
            self._advance()
            return Unary(tok, self._unary())
        if tok == "-" and self._is_unary_minus():
            self._advance()
            return Unary("-", self._unary())
        return self._primary()

    def _is_unary_minus(self) -> bool:
        return self.prev is None or self.prev == "(" or \
            self.prev in _PRECEDENCE

    def _primary(self) -> Node:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of expression")
        if tok == "(":
            self._advance()
            inner = self._expr(0)
            if self._peek() != ")":
                raise ParseError("missing closing ')'")
            self._advance()
            return inner
        self._advance()
        if re.match(r"^0[xX][0-9a-fA-F]+$", tok):
            return Const(int(tok, 16))
        if re.match(r"^\d+$", tok):
            return Const(int(tok, 10))
        if re.match(r"^[A-Za-z_]\w*$", tok):
            return Var(tok)
        raise ParseError(f"unexpected token {tok!r}")


def parse_expr(text: str) -> Node:
    """Parse a C expression into an AST; raises ParseError on bad syntax."""
    return _Parser(_tokenize(text)).parse()


def node_to_c(node: Node) -> str:
    """Best-effort C rendering of the AST (fully parenthesized)."""
    if isinstance(node, Const):
        return str(node.value)
    if isinstance(node, Var):
        return node.name
    if isinstance(node, Unary):
        return f"({node.op}{node_to_c(node.operand)})"
    return f"({node_to_c(node.left)} {node.op} {node_to_c(node.right)})"


# ---------------------------------------------------------------------------
# z3 lowering (32-bit bit-vector semantics)
# ---------------------------------------------------------------------------

def _require_z3() -> int:
    """Structured error + exit code when z3 is missing (return, not raise —
    keeps main() callable in-process for the degrade-path tests)."""
    if z3 is None:
        return _fail("z3-solver is not installed — run: uv pip install "
                     "z3-solver (in the workspace venv), then re-run "
                     "opaque-pred; --help works without z3")
    return -1  # z3 present: no error


def _to_bv(e: "z3.ExprRef", width: int) -> "z3.ExprRef":
    """Boolean -> bit-vector 1/0 (C truthiness); bit-vectors pass through."""
    if z3.is_bool(e):
        return z3.If(e, z3.BitVecVal(1, width), z3.BitVecVal(0, width))
    return e


def _truthy(e: "z3.ExprRef") -> "z3.ExprRef":
    """Bit-vector -> boolean (nonzero = true); booleans pass through."""
    if z3.is_bool(e):
        return e
    return e != 0


def build_z3(node: Node, width: int = DEFAULT_WIDTH) -> "z3.ExprRef":
    """Lower the AST to z3 with wrap-around `width`-bit semantics."""
    if isinstance(node, Const):
        return z3.BitVecVal(node.value, width)
    if isinstance(node, Var):
        return z3.BitVec(node.name, width)
    if isinstance(node, Unary):
        inner = build_z3(node.operand, width)
        if node.op == "~":
            return ~_to_bv(inner, width)
        if node.op == "-":
            return -_to_bv(inner, width)
        # "!" : C logical not — nonzero becomes 0, zero becomes 1.
        return z3.Not(_truthy(inner))
    left = build_z3(node.left, width)
    right = build_z3(node.right, width)
    op = node.op
    if op == "&&":
        return z3.And(_truthy(left), _truthy(right))
    if op == "||":
        return z3.Or(_truthy(left), _truthy(right))
    if op in ("==", "!=", "<", ">", "<=", ">="):
        # Unsigned comparisons: Ghidra emits unsigned ops by default.
        lb, rb = _to_bv(left, width), _to_bv(right, width)
        return {
            "==": lb == rb, "!=": lb != rb,
            "<": lb < rb, ">": lb > rb,
            "<=": lb <= rb, ">=": lb >= rb,
        }[op]
    lb, rb = _to_bv(left, width), _to_bv(right, width)
    # Unsigned division/remainder/shift — same rationale.
    return {
        "+": lb + rb, "-": lb - rb, "*": lb * rb,
        "/": z3.UDiv(lb, rb), "%": z3.URem(lb, rb),
        "&": lb & rb, "|": lb | rb, "^": lb ^ rb,
        "<<": lb << rb, ">>": z3.LShR(lb, rb),
    }[op]


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def check_predicate(expr_text: str, width: int = DEFAULT_WIDTH,
                    timeout_ms: int = TIMEOUT_MS) -> dict:
    """Opaque-predicate classification via two solver passes.

    Returns {kind: always_true|always_false|unknown, simplified: int|None}.
    Raises ParseError on bad syntax.
    """
    node = parse_expr(expr_text)
    expr = _truthy(build_z3(node, width))
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.push()
    solver.add(z3.Not(expr))
    not_sat = solver.check()
    solver.pop()
    if not_sat == z3.unsat:
        return {"kind": "always_true", "simplified": 1}
    solver.push()
    solver.add(expr)
    is_sat = solver.check()
    solver.pop()
    if is_sat == z3.unsat:
        return {"kind": "always_false", "simplified": 0}
    return {"kind": "unknown", "simplified": None}


def check_equivalence(lhs_text: str, rhs_text: str,
                      width: int = DEFAULT_WIDTH,
                      timeout_ms: int = TIMEOUT_MS) -> dict:
    """MBA equivalence proof: lhs != rhs unsat => equivalent.

    Returns {equivalent: bool, rewrite: str|None}. Raises ParseError on
    bad syntax.
    """
    lhs = _to_bv(build_z3(parse_expr(lhs_text), width), width)
    rhs = _to_bv(build_z3(parse_expr(rhs_text), width), width)
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(lhs != rhs)
    if solver.check() == z3.unsat:
        return {"equivalent": True, "rewrite": rhs_text}
    return {"equivalent": False, "rewrite": None}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fail(message: str) -> int:
    """Structured error JSON on stderr, exit code 2 (returned, not raised —
    in-process callers like the degrade-path tests get the code back)."""
    print(json.dumps({"error": message, "exit_code": EXIT_ERROR}),
          file=sys.stderr)
    return EXIT_ERROR


def _emit(args: argparse.Namespace, json_obj: dict,
          reproduce_rows: dict, text_line: str, exit_code: int) -> int:
    if args.reproduce:
        for key, value in reproduce_rows.items():
            print(f"{key}={value}")
    elif args.json:
        print(json.dumps(json_obj, ensure_ascii=False))
    else:
        print(text_line)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="opaque-pred",
        description="z3 opaque-predicate check / MBA simplifier (issue #306)")
    ap.add_argument("--expr", metavar="EXPR",
                    help="C expression to classify (quote it, e.g. "
                         "\"x >= 0 || x < 0\")")
    ap.add_argument("--simplify", metavar="\"LHS -> RHS\"",
                    help="MBA equivalence pair: prove LHS == RHS and emit "
                         "RHS as the rewrite suggestion")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH, metavar="N",
                    help="bit width for the wrap-around model "
                         f"(default {DEFAULT_WIDTH})")
    ap.add_argument("--json", action="store_true",
                    help="emit a single JSON object on stdout")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines for the kunglao L1 "
                         "mechanical gate")
    args = ap.parse_args(argv)

    if not args.expr and not args.simplify:
        return _fail("no mode selected: pass --expr EXPR or "
                     '--simplify "LHS -> RHS" (see --help)')
    if args.width <= 0:
        return _fail(f"invalid --width {args.width}: expected a positive "
                     "integer (e.g. 32 or 64)")
    missing_z3 = _require_z3()
    if missing_z3 != -1:
        return missing_z3

    if args.simplify:
        lhs, sep, rhs = args.simplify.partition("->")
        if not sep or not lhs.strip() or not rhs.strip():
            return _fail(f"invalid --simplify {args.simplify!r}: expected "
                         '"LHS -> RHS" with both sides non-empty (see --help)')
        lhs, rhs = lhs.strip(), rhs.strip()
        try:
            result = check_equivalence(lhs, rhs, args.width)
        except RecursionError:
            return _fail("expression too deeply nested (recursion limit) — "
                         "simplify the expression or raise the recursion limit")
        except ParseError as exc:
            return _fail(f"parse error in --simplify {args.simplify!r}: "
                         f"{exc} — check the C expression syntax (see --help)")
        equivalent = result["equivalent"]
        return _emit(
            args,
            {"tool": "opaque-pred", "mode": "simplify", "lhs": lhs, "rhs": rhs,
             "width": args.width, "equivalent": equivalent,
             "rewrite": result["rewrite"], "timeout_ms": TIMEOUT_MS},
            {"tool": "opaque-pred", "mode": "simplify", "lhs": lhs, "rhs": rhs,
             "width": args.width,
             "equivalent": "yes" if equivalent else "no",
             "rewrite": result["rewrite"] if result["rewrite"] else "none"},
            f"equivalent={'yes' if equivalent else 'no'} "
            f"rewrite={result['rewrite'] if result['rewrite'] else 'none'}",
            EXIT_DECIDED if equivalent else EXIT_UNKNOWN,
        )

    try:
        result = check_predicate(args.expr, args.width)
    except RecursionError:
        return _fail("expression too deeply nested (recursion limit) — "
                     "simplify the expression or raise the recursion limit")
    except ParseError as exc:
        return _fail(f"parse error in --expr {args.expr!r}: {exc} — check "
                     f"the C expression syntax (see --help)")
    kind = result["kind"]
    simplified = result["simplified"]
    decided = kind in ("always_true", "always_false")
    simplified_text = str(simplified) if simplified is not None else "none"
    return _emit(
        args,
        {"tool": "opaque-pred", "mode": "expr", "expr": args.expr,
         "width": args.width, "kind": kind, "simplified": simplified,
         "timeout_ms": TIMEOUT_MS},
        {"tool": "opaque-pred", "mode": "expr", "expr": args.expr,
         "width": args.width, "kind": kind, "simplified": simplified_text},
        f"kind={kind} simplified={simplified_text}",
        EXIT_DECIDED if decided else EXIT_UNKNOWN,
    )


if __name__ == "__main__":
    sys.exit(main())
