from agent_memory_kit import MemoryEngine, Message, Observation, Scope, SessionMemory
from agent_memory_kit.adapters import InMemoryStore

scope = Scope("demo", "user-1")
engine = MemoryEngine(InMemoryStore())
engine.observe(
    scope, Observation("event-1", "preference", 1, "Vegetarian meals", ("settings:1",))
)
sessions = SessionMemory()
sessions.append(scope, "chat-1", Message("m1", "user", "Plan dinner"), ttl=3600)
print(engine.active(scope)[0].content)
