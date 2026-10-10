# Architecture

- Evidence-backed long-term memory, source versions and idempotent events.
- User correction protection, logical forgetting and canonical retrieval validation.
- MongoDB aggregate storage and a reference cosine vector adapter.
- Tenant/user/session isolation, message replay checks and fixed session TTL.
- Injectable summaries with revision checks against concurrent mutations.

Session storage is process-local and synchronous. Session TTL expires the whole session; long-term memories do not yet expire automatically. Confidence is not a general importance score. Summaries are supplied by your callback; no model or automatic extraction is bundled. Forgetting is logical revocation, not guaranteed erasure of backups. Canonical aggregates and session histories grow without compaction. Remote vector adapters, production session persistence and ranking research remain future work.

The three repositories have separate release cycles. Versioned Agent Memory owns canonical memory and reference session storage. Agent Context Builder owns context assembly and budgeting. Agent Strategy Eval owns experiments and measurement; callbacks can target either library or unrelated applications.
