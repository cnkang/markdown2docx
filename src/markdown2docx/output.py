"""Stage DOCX output and publish without following mutable destination paths."""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import stat
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def _windows_api() -> tuple[Any, Any, Any]:
    """Load the Windows handle APIs without importing them on other platforms."""
    import ctypes
    from ctypes import wintypes
    from typing import Any, cast

    windows = cast(Any, ctypes)
    kernel = windows.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        getattr(wintypes, "LPCWSTR", ctypes.c_wchar_p),
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = getattr(wintypes, "BOOL", ctypes.c_int)
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.restype = getattr(
        wintypes, "BOOL", ctypes.c_int
    )
    return windows, kernel, wintypes


def open_windows_resource(path: Path, *, directory: bool) -> int:
    """Pin every Windows path component, rejecting links and reparse points."""
    import msvcrt

    windows, kernel, wintypes = _windows_api()

    class Attributes(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    absolute = os.path.abspath(path)
    anchor = os.path.splitdrive(absolute)[0] + os.sep
    components: list[str] = []
    current = anchor
    components.append(current)
    for part in absolute[len(anchor) :].split(os.sep):
        if not part:
            continue
        current = os.path.join(current, part)
        components.append(current)
    handles: list[int] = []
    try:
        for index, component in enumerate(components):
            is_directory = index < len(components) - 1 or directory
            attributes = 0x02000000 | (0x00200000 if is_directory else 0)
            handle = kernel.CreateFileW(
                str(component), 0x80, 0x3, None, 3, attributes, None
            )
            if handle == ctypes.c_void_p(-1).value:
                raise windows.WinError(windows.get_last_error())
            handles.append(handle)
            info = Attributes()
            if not kernel.GetFileInformationByHandleEx(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):
                raise windows.WinError(windows.get_last_error())
            if info.attributes & 0x400:
                raise OSError(f"Refusing resource reparse point: {component}")
            if is_directory and not info.attributes & 0x10:
                raise OSError(f"Resource directory is not a directory: {component}")
            if not is_directory and not info.attributes & 0x20:
                raise OSError(f"Resource is not a regular file: {component}")
        descriptor: int = msvcrt.open_osfhandle(  # type: ignore[attr-defined]
            handles.pop(), os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
        return descriptor
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def _open_directory(path: str | Path) -> int:
    """Open one directory without following a final symbolic link."""
    if os.stat not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        raise OSError("Secure DOCX publication is not supported on this platform")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(f"Resource is not a directory: {path}")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_parent(path: Path) -> int:
    """Open/create each directory without following untrusted symbolic links."""
    required = (os.open, os.mkdir, os.stat, os.rename, os.link, os.unlink, os.rmdir)
    if not all(function in os.supports_dir_fd for function in required) or not hasattr(
        os, "O_NOFOLLOW"
    ):
        raise OSError("Secure DOCX publication is not supported on this platform")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    absolute = path.absolute()
    descriptor = _open_directory(absolute.anchor)
    root = os.fstat(descriptor)
    components = list(absolute.parts[1:])
    followed_links = 0
    try:
        while components:
            component = components.pop(0)
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as error:
                entry = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                parent = os.fstat(descriptor)
                # Permit system-owned aliases such as macOS /var and /tmp only
                # when an unprivileged directory writer cannot replace them.
                trusted_alias = (
                    component in {"var", "tmp", "etc"}
                    and (parent.st_dev, parent.st_ino) == (root.st_dev, root.st_ino)
                    and stat.S_ISLNK(entry.st_mode)
                    and entry.st_uid == 0
                    and parent.st_uid == 0
                    and not parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                )
                if not trusted_alias or followed_links >= 40:
                    raise OSError(
                        f"Refusing unsafe output directory component: {component}"
                    ) from error
                target = Path(os.readlink(component, dir_fd=descriptor))
                followed_links += 1
                if target.is_absolute():
                    os.close(descriptor)
                    descriptor = os.open(target.anchor, flags)
                    components = list(target.parts[1:]) + components
                else:
                    components = list(target.parts) + components
                continue
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _check_destination(name: str, descriptor: int, overwrite: bool) -> None:
    try:
        entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(entry.st_mode):
        raise OSError("Refusing to publish DOCX through symlink output path")
    if not overwrite:
        raise FileExistsError(f"Output file already exists: {name}")
    if not stat.S_ISREG(entry.st_mode):
        raise OSError(f"Output destination must be a regular file: {name}")


def _publish(source: Path, destination: Path, parent: int, overwrite: bool) -> None:
    """Copy privately on the destination filesystem, then atomically publish."""
    staging_name = f".markdown2docx-{uuid.uuid4().hex}"
    os.mkdir(staging_name, mode=0o700, dir_fd=parent)
    staging = os.open(
        staging_name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent,
    )
    try:
        info = os.fstat(staging)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise OSError("Output staging directory is not private")
        file_descriptor = os.open(
            "document.docx",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=staging,
        )
        with os.fdopen(file_descriptor, "wb") as target, source.open("rb") as original:
            shutil.copyfileobj(original, target)
        _check_destination(destination.name, parent, overwrite)
        if overwrite:
            # rename replaces a raced-in link itself, never its target.
            os.rename(
                "document.docx", destination.name, src_dir_fd=staging, dst_dir_fd=parent
            )
        else:
            # link fails atomically if any directory entry already exists.
            os.link(
                "document.docx",
                destination.name,
                src_dir_fd=staging,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink("document.docx", dir_fd=staging)
        os.close(staging)
        with contextlib.suppress(OSError):
            os.rmdir(staging_name, dir_fd=parent)


def _writer_temporary_root() -> Path:
    """Use a stable OS namespace rather than an arbitrary TMPDIR pathname."""
    # verified ownership and sticky permissions below
    root = Path(
        "/private/tmp" if sys.platform == "darwin" else "/tmp"  # nosec B108
    )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root.anchor, flags)
    try:
        for component in root.parts[1:]:
            parent = os.fstat(descriptor)
            if parent.st_uid != 0 or parent.st_mode & 0o022:
                raise OSError("System temporary directory has an unsafe ancestor")
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        directory = os.fstat(descriptor)
        if directory.st_uid != 0 or (
            directory.st_mode & 0o022 and not directory.st_mode & stat.S_ISVTX
        ):
            raise OSError("System temporary directory is not protected")
        return root
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def staged_docx_output(destination: Path, *, overwrite: bool = True) -> Iterator[Path]:
    """Yield a private writer path and safely publish it after successful use."""
    if os.name == "nt":
        with _windows_output(destination, overwrite=overwrite) as source:
            yield source
        return
    parent = _open_parent(destination.parent)
    try:
        _check_destination(destination.name, parent, overwrite)
        with tempfile.TemporaryDirectory(
            prefix="markdown2docx-", dir=_writer_temporary_root()
        ) as directory:
            source = Path(directory) / "document.docx"
            yield source
            _publish(source, destination, parent, overwrite)
    finally:
        os.close(parent)


@contextlib.contextmanager
def _windows_output(destination: Path, *, overwrite: bool) -> Iterator[Path]:
    """Pin Windows directory handles without delete sharing; reject reparse points.

    Omitting FILE_SHARE_DELETE prevents ancestors from being renamed/replaced
    while path-based writing and publication are in progress.
    """
    import ctypes

    windows, kernel, wintypes = _windows_api()

    class Attributes(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    handles = []

    def pin(path: Path) -> None:
        handle = kernel.CreateFileW(str(path), 0x80, 0x3, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise windows.WinError(windows.get_last_error())
        info = Attributes()
        if not kernel.GetFileInformationByHandleEx(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel.CloseHandle(handle)
            raise windows.WinError(windows.get_last_error())
        if info.attributes & 0x400 or not info.attributes & 0x10:
            kernel.CloseHandle(handle)
            raise OSError(f"Refusing unsafe output directory/reparse point: {path}")
        handles.append(handle)

    absolute = destination.absolute()
    try:
        for ancestor in reversed([absolute.parent, *absolute.parent.parents]):
            ancestor.mkdir(exist_ok=True)
            pin(ancestor)
        if absolute.is_symlink():
            raise OSError("Refusing symlink output path")
        if absolute.exists() and (not overwrite or not absolute.is_file()):
            raise FileExistsError(f"Output file already exists: {absolute}")
        with tempfile.TemporaryDirectory(
            prefix=".markdown2docx-", dir=absolute.parent
        ) as temporary:
            pin(Path(temporary))
            try:
                source = Path(temporary) / "document.docx"
                yield source
                if absolute.is_symlink():
                    raise OSError("Refusing symlink output path")
                if overwrite:
                    os.replace(source, absolute)
                else:
                    os.link(source, absolute)
            finally:
                kernel.CloseHandle(handles.pop())
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)
