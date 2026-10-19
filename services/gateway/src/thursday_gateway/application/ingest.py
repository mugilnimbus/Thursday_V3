"""Taking in the agents' events: store each new one, apply it, and tell the connected clients."""

from thursday_contracts.events import EventEnvelope

from thursday_gateway.application.hub import Hub, event_message
from thursday_gateway.application.ports import EventLog


class EventIngest:
    def __init__(self, log: EventLog, hub: Hub) -> None:
        self._log = log
        self._hub = hub

    def accept(self, events: list[EventEnvelope]) -> tuple[int, int, dict[str, int]]:
        """Returns how many were new, how many were already known, and the last sequence number per sender.
        Repeating a batch changes nothing, so a sender that got no answer can send it again."""
        accepted, duplicates = self._log.ingest(events)
        for pos, event in accepted:
            self._hub.publish(event_message(pos, event))
        return len(accepted), duplicates, self._log.last_seq()
