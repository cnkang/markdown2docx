"""Validate DOCX resource budgets before any document/XML parser loads it."""

from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .config import LimitsConfig
from .exceptions import ValidationError


def validate_archive(path: Path, limits: LimitsConfig) -> None:
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            failures = []
            if len(names) != len(set(names)):
                failures.append("Duplicate DOCX archive entries")
            if len(entries) > limits.archive_entries:
                failures.append("DOCX exceeds limits.archive_entries")
            if sum(entry.file_size for entry in entries) > limits.archive_bytes:
                failures.append("DOCX exceeds limits.archive_bytes")
            if any(
                entry.file_size > limits.xml_bytes
                for entry in entries
                if entry.filename.endswith(".xml")
            ):
                failures.append("DOCX exceeds limits.xml_bytes")
            if failures:
                raise ValidationError(str(path), failures)
    except BadZipFile as exc:
        raise ValidationError(str(path), ["Invalid DOCX archive"]) from exc
