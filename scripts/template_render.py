#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""template_render.py — shared {{param}} template rendering primitives (#362).

Issue #362: the repo had TWO incompatible template rendering systems —
scripts/template_gen.py ({{lowercase}} regex single-pass + fail-closed
leftover detection) and scripts/kunglao-init.py (<UPPERCASE> str.replace
chain with NO leftover detection — an unfilled placeholder shipped silently
into generated CLAUDE.md). This module is the single source of the engine
primitives both callers now share:

  render(template_text, params)      single-pass {{KEY}} substitution
  leftover_placeholders(text)        unfilled keys (template defect)
  TemplateRenderError                 fail-closed exception naming leftovers
  PLACEHOLDER                        the compiled pattern (exported for
                                     callers that scan rendered text)

Semantics (frozen by tests/test_template_gen.py + test_renderer_unify.py):
  * substitution is single-pass and verbatim — substituted values are never
    re-scanned, so a value containing "{{x}}" stays literal;
  * placeholders with no matching key are left intact so
    leftover_placeholders() can report them AFTER rendering;
  * keys match [A-Za-z0-9_]+ (template_gen has always allowed mixed case;
    kunglao-init uses lowercase keys).

stdlib only, no third-party imports.
"""
from __future__ import annotations

import re

PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")


class TemplateRenderError(RuntimeError):
    """Template defect: placeholders survived rendering (fail-closed)."""


def render(template_text: str, params: dict[str, str]) -> str:
    """Replace every {{KEY}} placeholder with params[KEY] (single pass,
    verbatim — substituted values are never re-scanned). Placeholders with no
    matching key are left intact so leftover_placeholders() can report them."""
    def _sub(m: re.Match[str]) -> str:
        return params.get(m.group(1), m.group(0))
    return PLACEHOLDER.sub(_sub, template_text)


def leftover_placeholders(text: str) -> list[str]:
    """Placeholder keys still present after rendering (template defect)."""
    return sorted(set(PLACEHOLDER.findall(text)))


def render_strict(template_text: str, params: dict[str, str],
                  *, source: str = "template") -> str:
    """render() + fail-closed check: any leftover placeholder raises
    TemplateRenderError naming the source and the unfilled keys. Callers that
    must never ship a partial render (kunglao-init CLAUDE.md) use this."""
    rendered = render(template_text, params)
    leftovers = leftover_placeholders(rendered)
    if leftovers:
        raise TemplateRenderError(
            f"{source}: placeholder(s) not covered by render params: "
            f"{', '.join(leftovers)}")
    return rendered
