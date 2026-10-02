# Case 3: Desktop agent license protocol

> One-page sanitized battle report. The target is a commercial desktop
> product; disclosure is deliberately minimal — no recovered secrets,
> parameter values, or protocol field values are published.

## Target

The local protocol and license-verification surface of a desktop AI coding
agent: the exchange by which the client proves a valid license. The task:
characterize the verification exchange and reproduce the challenge/response
computation offline for every recorded exchange.

## Defense surface

- Local IPC/protocol framing around the verification exchange
- An obfuscated verification module
- A challenge/response handshake (server-issued challenge, computed response)
- Anti-tamper checks around the verification path

## Agent route

1. Surface mapping of the local protocol: endpoints, message framing, and
   where verification traffic flows.
2. Location of the verification module inside the obfuscated code.
3. Capture of live challenge/response exchanges.
4. Derivation of the handshake structure: what the challenge carries and
   what the response must be a function of.
5. Offline re-implementation of the response computation.
6. Replay verification against the recorded exchanges; an independent
   verifier re-derived the characterization blind before any claim was
   promoted.

## Verdict

The challenge/response protocol was fully characterized, and the response
computation was reproduced byte-exact against every recorded exchange.

## What this demonstrates

Cross-domain coverage (desktop/protocol lane) with the same mechanical-oracle
discipline as the native and web lanes: characterization claims settle only
through independent blind verification and replay, not self-assessment.
