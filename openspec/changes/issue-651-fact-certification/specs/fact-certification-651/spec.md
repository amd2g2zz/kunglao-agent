# fact-certification-651 delta — issue-651-fact-certification

## ADDED Requirements

### Requirement: A terminal fact status is honored only when register-backed

`lint_facts.certification_defects(fm, body, proven, fact_ids)` SHALL
return the fact grammar's error defects PLUS a certification defect
when the fact carries a PROVEN/VERIFIED status that is not backed by
the register (every claim the fact cites — exact frontmatter citation
via `collect_claim_refs` — must be PROVEN in claim-register.yaml, read
via `read_register_proven`). A terminal status without any claim
citation is uncertifiable. Non-terminal statuses carry no
certification defect (the grammar still applies).

#### Scenario: junk VERIFIED facts before promotion are uncertified

- **WHEN** a fact carries `status: VERIFIED` citing C-005 and the
  register carries C-005 as PARTIALLY-VERIFIED
- **THEN** the certification defects name the missing register backing

#### Scenario: a promotion-backed terminal status certifies

- **WHEN** the fact cites only claims the register carries as PROVEN
  and the fact grammar is clean
- **THEN** the certification defects are empty

#### Scenario: a claim-less terminal status is uncertifiable

- **WHEN** a fact carries a terminal status and cites no claim
- **THEN** the certification defects name the missing citation

### Requirement: fact_face counts only certified terminal facts

`rlvr.state.fact_face` SHALL count a fact toward `verified` only when
its terminal status survives the certification gate; `count` SHALL
remain the number of fact files (presence unchanged; lint owns
loudness).

#### Scenario: the two-junk-files farm stops lifting Φ

- **WHEN** a workspace carries two junk facts with
  `status: VERIFIED` citing a PARTIALLY-VERIFIED claim
- **THEN** `fact_face(ws)["verified"] == 0` (previously 2)

#### Scenario: promotion lights the fact dim honestly

- **WHEN** the register promotes the cited claim to PROVEN
- **THEN** the same facts count as verified

### Requirement: facts_citing parses frontmatter and requires certification

`e2e.checkpoints._facts_citing` SHALL count a fact only when its
frontmatter parses, the fact grammar is clean, the claim is an EXACT
frontmatter citation (`collect_claim_refs` contains the claim), and a
terminal status is register-backed. The body-substring scan SHALL be
retired. Malformed files count as 0.

#### Scenario: a body mention without frontmatter citation counts nothing

- **WHEN** a fact's body mentions the claim id but the frontmatter
  carries no claim citation
- **THEN** the fact does not count toward `facts_citing`

#### Scenario: the farming chain nets zero through the settle path

- **WHEN** the two-junk-files workspace settles a DISPATCHED outcome
  through `_settle_dispatch_outcome`
- **THEN** the credit equals the no-facts baseline (0.5), the
  transition row banks it, the store row carries `facts_citing: 0`,
  and the posterior observation matches the no-facts run
