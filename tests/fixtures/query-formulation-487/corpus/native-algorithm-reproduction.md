---
name: native-algorithm-reproduction
description: Discrimination and verification moves for algorithm reproduction through a
  native emulation harness on a mobile native library — constant-search traps, key
  provenance ladders, digest-shape priors.
domain: patterns
family: decode
---
# Native algorithm reproduction (emulation half)

Deliberately phrased without the worker-jargon vocabulary (the decoy
card jargon-workflow.md carries it instead): this card is the fixture's
proof that formulation — the format facet's packaging/emulation terms —
retrieves method material the raw trigger fragment cannot.

## When to Use

- A mobile native library computes a value whose family is still
  ambiguous.
- A constant byte-search over the module keeps missing a constant the
  algorithm provably uses.

## Moves

Run the target through a native emulation harness (unidbg-class) and
observe the digest-shape priors: 32-byte outputs orient toward digest
families, modulus-length blocks toward asymmetric families. Constant
searches must try both endiannesses and the split-constant trap
(movz/movk pairs hide 64-bit values as two 32-bit halves).
