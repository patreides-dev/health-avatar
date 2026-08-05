from dataclasses import dataclass
from typing import Protocol

from app.ingestion.contracts import AdapterRequest, AdapterResult


class IngestionAdapter(Protocol):
    name: str
    version: str
    schema_version: str
    artifact_kinds: frozenset[str]
    media_types: frozenset[str]
    extensions: frozenset[str]

    def inspect(self, request: AdapterRequest) -> AdapterResult: ...


class AdapterNotFoundError(LookupError):
    pass


@dataclass
class AdapterRegistry:
    adapters: list[IngestionAdapter]

    def register(self, adapter: IngestionAdapter) -> None:
        if any(existing.name == adapter.name for existing in self.adapters):
            raise ValueError(f"Adapter {adapter.name!r} is already registered")
        self.adapters.append(adapter)

    def select(
        self,
        *,
        artifact_kind: str,
        media_type: str,
        filename: str | None,
        explicit_name: str | None = None,
    ) -> IngestionAdapter:
        extension = "." + filename.rsplit(".", 1)[1].lower() if filename and "." in filename else ""
        matches = [
            adapter
            for adapter in self.adapters
            if (explicit_name is None or adapter.name == explicit_name)
            and artifact_kind in adapter.artifact_kinds
            and (media_type in adapter.media_types or extension in adapter.extensions)
        ]
        if len(matches) != 1:
            raise AdapterNotFoundError("No unique registered adapter supports this artifact")
        return matches[0]
