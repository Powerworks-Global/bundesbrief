# Vendored `trust_layer`

This package is a **verbatim vendored copy** of the standalone
[`trust-layer`](https://github.com/Willpower-hadisfar/trust-layer) library
(Apache 2.0, same author as this project), taken at commit
`cf91a5534b625af08da80fe66a5cad558d3ed958`.

**Why vendored instead of a declared dependency:** the upstream repository is
private, so a forge-address dependency would make this project uninstallable
for anyone without read access — including hackathon judges cloning this
submission. Vendoring keeps the real library (rather than a hand-maintained
copy) importable under its canonical `trust_layer` name with `make install`
alone.

**Follow-up (tracked in ROADMAP.md):** once `trust-layer` is published
(public repo or PyPI), replace this directory with a version-pinned
dependency.

Do not edit these files locally — pull upstream changes and re-vendor.
The copy is unmodified: `__init__.py`, `confidence.py`, `gate.py`,
`ledger.py`, `trust.py`.

Note: Bundesbrief's own `bundesbrief.ledger` (the TrustContract hash-chained
justification ledger) deliberately keeps its own wire format — the existing
chain could not be re-hashed under `trust_layer.ledger`'s different entry
format without retroactively invalidating already-logged entries. See
ADR-002.
