# Validation

## 0.1.0 — October 9, 2026

- Python 3.12.13 on macOS: 89 passed.
- Ruff lint and format checks, strict mypy, examples and source/wheel builds passed.
- Service-free examples use synthetic records, not production data.

Tests cover memory receipts/corrections/forgetting, scoped vectors, session replay, fixed TTL, and stale summaries after append, deletion, expiry or recreation. Mongo tests use mongomock; live Mongo adapter coverage also runs through ContextKit compatibility imports. This is not a scalability benchmark.

Packages are distributed through pinned GitHub releases, not a PyPI publication. Passing these checks does not establish compatibility with every Python version, production scale or downstream model behavior.
