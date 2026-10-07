# KVM-8 blocked-path workspace (#546, constructed)

GOAL: produce answer.txt in the workspace root — four lines,
each the 16-hex-char lowercase digest one program emits:
  probes/payload-0.bin .. probes/payload-2.bin (index order),
  then target/payload.bin last.

The payloads are programs for a private bytecode VM (the KVM-8
ISA — a container format and opcode map that exist nowhere else).
target/src/vm.rs is the reference interpreter.

Build note:
  rustc -O --edition 2021 -o vm target/src/vm.rs
  ./vm target/payload.bin        # prints "KVM-DIGEST <16 hex>"

toolbox/peekbin and toolbox/opcount inspect containers;
toolbox/fold8 and toolbox/refold8 are pipeline decoy folds —
no toolbox tool computes the answer, and no stock digest family
(sha*/md5*/cksum*) reproduces it. The ISA is documented only by
the interpreter source: emulate it or run it.
