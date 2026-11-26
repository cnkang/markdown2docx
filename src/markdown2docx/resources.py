"""Explicit boundaries for documents with external resources or filters."""

import errno
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .exceptions import ConversionError

if TYPE_CHECKING:
    from .output import PinnedDirectory


def _outside_resource_directory() -> ConversionError:
    return ConversionError("", "Image is outside the document resource directory")


def _lexical_paths(root: Path, path: Path) -> tuple[Path, Path]:
    """Normalize paths without consulting the filesystem or resolving links."""
    normalized_root = Path(os.path.abspath(os.path.normpath(os.fspath(root))))
    candidate = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    try:
        inside = os.path.commonpath(
            [
                os.path.normcase(os.fspath(normalized_root)),
                os.path.normcase(os.fspath(candidate)),
            ]
        ) == os.path.normcase(os.fspath(normalized_root))
    except ValueError:
        inside = False
    if not inside:
        raise _outside_resource_directory()
    return normalized_root, candidate


def _open_restricted_parent(root: Path, candidate: Path) -> tuple[int, str]:
    """Open the pinned document root, then candidate parents without following links."""
    from .output import _open_parent

    if root.anchor != candidate.anchor:
        raise _outside_resource_directory()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    components = candidate.relative_to(root).parts
    descriptor: int | None = None
    succeeded = False
    try:
        descriptor = _open_parent(root)
        for component in components[:-1]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as error:
                entry = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISLNK(entry.st_mode):
                    raise ConversionError(
                        "", "Image resource contains a symbolic link"
                    ) from error
                raise
            os.close(descriptor)
            descriptor = child
        if descriptor is None:
            raise ConversionError("", "Unable to validate image resource safely")
        result = descriptor, components[-1]
        succeeded = True
        return result
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise ConversionError("", "Image resource does not exist") from exc
        if isinstance(exc, NotADirectoryError):
            raise _outside_resource_directory() from exc
        raise ConversionError("", "Unable to validate image resource safely") from exc
    finally:
        if not succeeded and descriptor is not None:
            os.close(descriptor)


def _validate_restricted_image(root: Path, path: Path) -> str:
    normalized_root, candidate = _lexical_paths(root, path)
    if os.path.normcase(os.fspath(candidate)) == os.path.normcase(
        os.fspath(normalized_root)
    ):
        raise ConversionError("", "Image resource must be a regular file")
    if os.name == "nt":
        from .output import open_windows_resource

        try:
            descriptor = open_windows_resource(candidate, directory=False)
        except FileNotFoundError as exc:
            raise ConversionError("", "Image resource does not exist") from exc
        except OSError as exc:
            if "reparse point" in str(exc):
                raise ConversionError(
                    "", "Image resource contains a reparse point"
                ) from exc
            raise ConversionError(
                "", "Unable to validate image resource safely"
            ) from exc
        else:
            os.close(descriptor)
        return str(candidate)
    if not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY")):
        raise ConversionError("", "Secure resource validation is unavailable")
    descriptor, name = _open_restricted_parent(normalized_root, candidate)
    try:
        details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISLNK(details.st_mode):
            raise ConversionError("", "Image resource is a symbolic link")
        if not stat.S_ISREG(details.st_mode):
            raise ConversionError("", "Image resource must be a regular file")
    except FileNotFoundError as exc:
        raise ConversionError("", "Image resource does not exist") from exc
    finally:
        os.close(descriptor)
    return str(candidate)


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
                ast["c"][2][0] = _validate_restricted_image(root, path)
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
    ast: Any,
    root: Path,
    destination: Path,
    *,
    max_bytes: int,
    workspace: PinnedDirectory | None = None,
) -> None:
    """Copy already-validated images into a private conversion workspace."""
    import uuid

    from .output import _open_parent

    if isinstance(ast, list):
        for item in ast:
            stage_local_resources(
                item, root, destination, max_bytes=max_bytes, workspace=workspace
            )
    elif isinstance(ast, dict):
        if ast.get("t") == "Image":
            source = Path(ast["c"][2][0])
            source = source if source.is_absolute() else root / source
            path = destination / (uuid.uuid4().hex + source.suffix)
            if os.name == "nt":
                from .output import open_windows_resource

                try:
                    descriptor = open_windows_resource(source, directory=False)
                except FileNotFoundError as exc:
                    raise ConversionError("", "Image resource does not exist") from exc
                except OSError as exc:
                    if "reparse point" in str(exc):
                        raise ConversionError(
                            "", "Image resource contains a reparse point"
                        ) from exc
                    raise ConversionError(
                        "", "Unable to stage image resource safely"
                    ) from exc
                original = os.fdopen(descriptor, "rb")
            else:
                posix_descriptor: int | None = None
                parent: int | None = None
                try:
                    parent = _open_parent(source.parent)
                    posix_descriptor = os.open(
                        source.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent
                    )
                    original = os.fdopen(posix_descriptor, "rb")
                    posix_descriptor = None
                except FileNotFoundError as exc:
                    raise ConversionError("", "Image resource does not exist") from exc
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        raise ConversionError(
                            "", "Image resource contains a symbolic link"
                        ) from exc
                    raise ConversionError(
                        "", "Unable to stage image resource safely"
                    ) from exc
                finally:
                    if posix_descriptor is not None:
                        os.close(posix_descriptor)
                    if parent is not None:
                        os.close(parent)
            try:
                if workspace is None:
                    target_context = path.open("xb")
                else:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if os.name != "nt":
                        flags |= os.O_NOFOLLOW
                    target_context = os.fdopen(
                        workspace.open_file(path.name, flags), "wb"
                    )
            except BaseException:
                original.close()
                raise
            with original, target_context as target:
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
            stage_local_resources(
                value, root, destination, max_bytes=max_bytes, workspace=workspace
            )
