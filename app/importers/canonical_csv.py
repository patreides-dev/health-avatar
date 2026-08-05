"""Compatibility entry point for the Version 0.1 canonical CSV command.

The implementation is now the registered staged adapter pipeline. Callers must provide an actor,
storage backend, and validated settings; there is no unauthenticated importer path.
"""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ImportBatch, Person, SourceSystem
from app.services.auth import Actor
from app.services.ingestion import IngestionError, ingest_csv
from app.services.storage import ArtifactStorage

ImportRequestError = IngestionError


def import_canonical_csv(
    session: Session,
    *,
    content: bytes,
    filename: str,
    source_system: SourceSystem,
    subject_person: Person,
    actor: Actor,
    storage: ArtifactStorage,
    settings: Settings,
) -> ImportBatch:
    """Run canonical CSV through artifact, adapter, candidate, and promotion services."""
    _, _, batch = ingest_csv(
        session,
        content=content,
        filename=filename,
        source_system=source_system,
        subject_person=subject_person,
        actor=actor,
        storage=storage,
        settings=settings,
    )
    return batch
