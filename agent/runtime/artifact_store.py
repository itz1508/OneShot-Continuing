"""Compatibility API: one implementation lives in system.runtime.artifact_store.store."""

from system.runtime.artifact_store.store import (
    ArtifactStoreError as ArtifactStoreError,
    DuplicateArtifactError as DuplicateArtifactError,
    ArtifactNotFoundError as ArtifactNotFoundError,
    StaleRevisionError as StaleRevisionError,
    ArtifactStore as ArtifactStore,
)
