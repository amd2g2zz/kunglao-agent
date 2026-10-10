# verifier-anchor-653 delta — issue-653-verifier-anchor

## ADDED Requirements

### Requirement: A verified verdict carries re-run receipts (the hybrid ruling)

The V-dispatch prompt SHALL mandate a re-run receipt block (`re-run:` /
`rc:` / `out-sha:`) for every reproduce command the verdict relies on
and SHALL state the recorded-output distrust rule. The landing gate
SHALL refuse a `verdict: verified` note carrying no well-formed
receipt: ONE warn, the verdict settles as absent (0.0 credit),
prediction settlement is skipped, and the promotion attempt is replaced
by a recorded refusal. A `refuted` verdict is exempt.

#### Scenario: verified without receipts banks nothing

- **WHEN** the verifier lands a note with `verdict: verified` and no
  receipt block
- **THEN** the engine warns once, the transition settles with no
  verify credit, no prediction settles from the note, and the
  promotion detail carries the refusal reason

#### Scenario: a well-formed receipt satisfies the gate

- **WHEN** the note carries `re-run: <cmd>` / `rc: 0` /
  `out-sha: <64 hex>` for at least one command
- **THEN** the verification proceeds exactly as before (settle +
  promotion attempt)

#### Scenario: malformed receipts count as absent

- **WHEN** a receipt block carries a non-integer rc or a short out-sha
- **THEN** the gate refuses the note (same refusal path)

### Requirement: The V-dispatch prompt is sibling-free

The engine-built V prompt SHALL reference exactly the target claim and
no sibling claim ids.

#### Scenario: the priming channel is pinned shut at the engine

- **WHEN** the V-dispatch prompt is built for claim C-004
- **THEN** the only claim id in the prompt text is C-004
