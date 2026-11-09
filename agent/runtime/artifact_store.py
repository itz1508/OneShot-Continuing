"""Compatibility API: one implementation lives in system.runtime.artifact_store.store."""

from system.runtime.artifact_store.store import (
    ArtifactNotFoundError as ArtifactNotFoundError,
    ArtifactStore as ArtifactStore,
    ArtifactStoreError as ArtifactStoreError,
    DuplicateArtifactError as DuplicateArtifactError,
    StaleRevisionError as StaleRevisionError,
)
