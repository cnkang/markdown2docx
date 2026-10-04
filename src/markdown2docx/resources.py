"""Explicit boundaries for documents with external resources or filters."""

from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .exceptions import ConversionError


def validate_resources(
    ast: Any, root: Path, *, offline: bool, restricted: bool
) -> None:
    """Check every image and raw node before asking Pandoc to read resources."""
    if isinstance(ast, list):
        for item in ast:
            validate_resources(item, root, offline=offline, restricted=restricted)
    elif isinstance(ast, dict):
        kind = ast.get("t")
        if restricted and kind in {"RawBlock", "RawInline"}:
            raise ConversionError("", "Raw content is unavailable in restricted mode")
        if kind == "Image":
            location = ast["c"][2][0]
            parsed = urlparse(location)
            if Path(location).is_absolute():
                parsed = urlparse(Path(location).as_uri())
            if offline or restricted:
                if parsed.scheme not in {"", "file"} or parsed.netloc:
                    raise ConversionError(
                        "", "Remote images are unavailable under this resource policy"
                    )
            if restricted:
                path = (
                    Path(url2pathname(parsed.path))
                    if parsed.scheme == "file"
                    else Path(unquote(parsed.path))
                )
                path = path if path.is_absolute() else root / path
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root.resolve()):
                    raise ConversionError(
                        "", "Image is outside the document resource directory"
                    )
                ast["c"][2][0] = str(resolved)
        for value in ast.values():
            validate_resources(value, root, offline=offline, restricted=restricted)


def validate_restricted_arguments(arguments: Sequence[str]) -> None:
    """Restricted documents cannot supply arbitrary Pandoc extension programs."""
    allowed = {"--number-sections", "--highlight-style", "--shift-heading-level-by"}
    expects_value = False
    for argument in arguments:
        if expects_value:
            if argument.startswith("-"):
                raise ConversionError("", "Missing restricted argument value")
            expects_value = False
            continue
        option = argument.split("=", 1)[0]
        if option not in allowed:
            raise ConversionError(
                "", f"Pandoc option is unavailable in restricted mode: {option}"
            )
        expects_value = option != "--number-sections" and "=" not in argument
    if expects_value:
        raise ConversionError("", "Missing restricted argument value")


def stage_local_resources(
    ast: Any, root: Path, destination: Path, *, max_bytes: int
) -> None:
    """Copy already-validated images into a private conversion workspace."""
    import os
    import stat
    import uuid

    from .output import _open_parent

    if isinstance(ast, list):
        for item in ast:
            stage_local_resources(item, root, destination, max_bytes=max_bytes)
    elif isinstance(ast, dict):
        if ast.get("t") == "Image":
            source = Path(ast["c"][2][0])
            source = source if source.is_absolute() else root / source
            path = destination / (uuid.uuid4().hex + source.suffix)
            if os.name == "nt":
                # Resource restriction is a policy check, not a Windows filesystem sandbox.
                original = source.open("rb")
            else:
                parent = _open_parent(source.parent)
                try:
                    descriptor = os.open(
                        source.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent
                    )
                    original = os.fdopen(descriptor, "rb")
                finally:
                    os.close(parent)
            with original, path.open("xb") as target:
                details = os.fstat(original.fileno())
                if not stat.S_ISREG(details.st_mode) or details.st_size > max_bytes:
                    raise ConversionError(
                        "", "Image exceeds resource size limit or is not a regular file"
                    )
                remaining = max_bytes + 1
                while chunk := original.read(min(1024 * 1024, remaining)):
                    remaining -= len(chunk)
                    if remaining <= 0:
                        raise ConversionError("", "Image exceeds resource size limit")
                    target.write(chunk)
            ast["c"][2][0] = str(path)
        for value in ast.values():
            stage_local_resources(value, root, destination, max_bytes=max_bytes)
