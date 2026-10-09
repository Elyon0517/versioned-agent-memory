"""MongoDB storage using one atomic, revision-guarded document per scope."""

from __future__ import annotations

from typing import Any

from agent_memory_kit.models import Scope, SubjectState


class MongoStore:
    def __init__(self, collection: Any) -> None:
        from pymongo import ReadPreference
        from pymongo.write_concern import WriteConcern

        self.collection = collection.with_options(
            read_preference=ReadPreference.PRIMARY, write_concern=WriteConcern("majority")
        )

    def load(self, scope: Scope) -> SubjectState:
        raw = self.collection.find_one({"_id": scope.key})
        if raw is None:
            return SubjectState()
        if raw.get("scope") != {"tenant": scope.tenant, "subject": scope.subject}:
            raise ValueError("stored scope does not match requested scope")
        return SubjectState.from_dict(raw)

    def compare_and_swap(
        self, scope: Scope, expected_revision: int, state: SubjectState
    ) -> bool:
        from pymongo.errors import DuplicateKeyError

        if state.revision != expected_revision + 1:
            raise ValueError("new revision must advance exactly once")
        document = {
            **state.to_dict(),
            "_id": scope.key,
            "scope": {"tenant": scope.tenant, "subject": scope.subject},
        }
        if expected_revision == 0:
            try:
                self.collection.insert_one(document)
                return True
            except DuplicateKeyError:
                return False
        result = self.collection.replace_one(
            {"_id": scope.key, "revision": expected_revision}, document, upsert=False
        )
        return bool(result.matched_count)
