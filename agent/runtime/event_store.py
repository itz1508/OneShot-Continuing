"""Compatibility API: one implementation lives in system.runtime.event_store.store."""

from system.runtime.event_store.store import (
    AppendOnlyEventStore as AppendOnlyEventStore,
    EventStore as EventStore,
)
