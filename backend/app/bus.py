"""A tiny in-process message bus.

Agents never call each other directly. They publish a message on a topic,
and any agent subscribed to that topic receives it. Every message is logged
so the UI can show the agents "talking" to each other.
"""
from __future__ import annotations

import itertools
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

_ids = itertools.count(1)


@dataclass
class Message:
    sender: str           # agent that sent it
    topic: str            # e.g. "funnel.anomaly"
    payload: dict         # structured data for other agents
    text: str             # plain-English summary for humans
    to: str = "all"       # intended receiver (for display)
    ts: float = 0.0
    id: int = field(default_factory=lambda: next(_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "ts": self.ts, "sender": self.sender, "to": self.to,
            "topic": self.topic, "text": self.text,
        }


class MessageBus:
    def __init__(self, log_size: int = 150):
        self._subs: dict[str, list[Callable[[Message], None]]] = defaultdict(list)
        self.log: deque[Message] = deque(maxlen=log_size)
        self.now: float = 0.0  # set by the engine every tick

    def subscribe(self, topic: str, handler: Callable[[Message], None]) -> None:
        self._subs[topic].append(handler)

    def publish(self, sender: str, topic: str, payload: dict, text: str,
                to: str = "all", log: bool = True) -> Message:
        msg = Message(sender=sender, topic=topic, payload=payload, text=text, to=to, ts=self.now)
        if log:
            self.log.append(msg)
        for handler in list(self._subs.get(topic, [])):
            handler(msg)
        return msg
