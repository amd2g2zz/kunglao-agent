# TF pipeline workspace (#356, constructed)

GOAL: produce answer.txt in the workspace root — seven lines,
each the 16-hex-char lowercase digest of one payload:
  probes/payload-0.bin .. probes/payload-5.bin (index order),
  then target/payload.bin last.

toolbox/ ships the pipeline tools. The stages hand off state
(blob -> stage state -> ... -> digest); no single tool computes
the answer, and more than one tool combination does.

Files: target/blob.enc (encrypted stage parameters),
target/payload.bin (main material), probes/*.bin (probe
payloads), toolbox/* (the pipeline tools).
