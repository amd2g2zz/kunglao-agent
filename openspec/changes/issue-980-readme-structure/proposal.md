## Why

#979 fixed the chart, but the README pair still fails as a document. The
`📋 Requirements` table links `[Toolchain](#-toolchain-by-target)`, and that
target is a `<details><summary>` — GitHub only mints anchors for headings, so
the link has never worked in either language. The "table of contents" at the
top is a plain string, not links, and it names eight items while the document
has twenty-one sections (two of those eight match no heading at all).

Worse for a bilingual reader: the English README has 21 second-level sections
and the Chinese has 19. `Subcommands` is a section in English and a
third-level heading in Chinese, and `What a run looks like` has no Chinese
counterpart — switching languages gives a different document.

## What Changes

- Give the toolchain block a real `### Toolchain by target` /
  `### 按目标分工具链` heading so the existing links resolve.
- Replace the plain-string TOC with real links covering every section
  except License.
- Restore EN/ZH parity: promote `命令` to a second-level section and add
  `一次运行长什么样`, the faithful Chinese counterpart of
  `What a run looks like`.
- Normalise four hyphen-as-dash uses to em dashes; convert two straight-quote
  pairs in Chinese prose to 「」.
- Keep the emoji headings and the visual language untouched — a structural
  pass, not a restyle.

Docs only. No code, no behaviour change.
