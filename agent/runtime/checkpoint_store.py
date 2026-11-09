"""Compatibility API: one implementation lives in system.runtime.checkpoint_store.store."""

from system.runtime.checkpoint_store.store import (
    CheckpointStoreError as CheckpointStoreError,
    CompetingWriterError as CompetingWriterError,
    StaleCheckpointError as StaleCheckpointError,
    InMemoryCheckpointStore as InMemoryCheckpointStore,
    CheckpointStore as CheckpointStore,
)
