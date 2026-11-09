"""Compatibility API: one implementation lives in system.runtime.checkpoint_store.store."""

from system.runtime.checkpoint_store.store import (
    CheckpointStore as CheckpointStore,
    CheckpointStoreError as CheckpointStoreError,
    CompetingWriterError as CompetingWriterError,
    InMemoryCheckpointStore as InMemoryCheckpointStore,
    StaleCheckpointError as StaleCheckpointError,
)
