from dataclasses import asdict, dataclass, field


class IndexingStatus:
    EMPTY = "EMPTY"
    FILES_UPLOADED = "FILES_UPLOADED"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"
    DIRTY = "DIRTY"


STATUS_LABELS = {
    IndexingStatus.EMPTY: "No files",
    IndexingStatus.FILES_UPLOADED: "Uploaded",
    IndexingStatus.INDEXING: "Indexing",
    IndexingStatus.READY: "Ready",
    IndexingStatus.FAILED: "Failed",
    IndexingStatus.DIRTY: "Dirty",
}

STATUS_COLORS = {
    IndexingStatus.EMPTY: "dim-red",
    IndexingStatus.FILES_UPLOADED: "yellow",
    IndexingStatus.INDEXING: "blue",
    IndexingStatus.READY: "green",
    IndexingStatus.FAILED: "red",
    IndexingStatus.DIRTY: "orange",
}


@dataclass
class IndexingResult:
    status: str
    step: str = ""
    files_indexed: int = 0
    chunks_indexed: int = 0
    full_rebuild: bool = False
    manifest_changed: bool = False
    errors: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

