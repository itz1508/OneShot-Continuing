"""Compatibility API: one implementation lives in system.runtime.event_store.store."""

from system.runtime.event_store.store import (
    EventStore as EventStore,
    AppendOnlyEventStore as AppendOnlyEventStore,
)
