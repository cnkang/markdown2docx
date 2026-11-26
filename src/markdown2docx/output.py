"""Stage DOCX output and publish without following mutable destination paths."""

from __future__ import annotations

import contextlib
import ctypes
import os
import platform
import shutil
import stat
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

FILE_READ_ATTRIBUTES = 0x80
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
CREATE_NEW = 1
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_TAG_INFO = 9
FILE_TYPE_DISK = 1
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class WindowsFileAttributes(ctypes.Structure):
    _fields_ = [("attributes", ctypes.c_uint32), ("tag", ctypes.c_uint32)]


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


class PinnedDirectory:
    """A directory identity that survives pathname replacement."""

    def __init__(self, path: Path, descriptor: int) -> None:
        self.path = path
        self.descriptor = descriptor

    def open_file(self, name: str, flags: int, mode: int = 0o600) -> int:
        if os.name == "nt":
            return os.open(self.path / name, flags, mode)
        return os.open(name, flags, mode, dir_fd=self.descriptor)

    def open_regular(self, name: str) -> int:
        if os.name == "nt":
            descriptor = open_windows_resource(self.path / name, directory=False)
        else:
            descriptor = self.open_file(name, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError(f"Resource is not a regular file: {name}")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def open_directory(self, name: str) -> int:
        if os.name == "nt":
            descriptor = open_windows_resource(self.path / name, directory=True)
        else:
            descriptor = self.open_file(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError(f"Resource is not a directory: {name}")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def make_directory(self, name: str) -> None:
        if os.name == "nt":
            (self.path / name).mkdir(mode=0o700)
        else:
            os.mkdir(name, mode=0o700, dir_fd=self.descriptor)

    def write_bytes(self, name: str, data: bytes, *, replace: bool = False) -> None:
        if os.name == "nt":
            descriptor = open_windows_writable(self.path / name, replace=replace)
            try:
                if replace:
                    os.ftruncate(descriptor, 0)
            except BaseException:
                os.close(descriptor)
                raise
        else:
            flags = os.O_WRONLY | os.O_CREAT
            flags |= os.O_TRUNC if replace else os.O_EXCL
            flags |= os.O_NOFOLLOW
            descriptor = self.open_file(name, flags)
        try:
            target = os.fdopen(descriptor, "wb")
        except BaseException:
            os.close(descriptor)
            raise
        with target:
            target.write(data)

    def remove_entry(self, name: str) -> None:
        """Remove an empty private directory entry without following a link."""
        if os.name == "nt":
            path = self.path / name
            if path.is_symlink():
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                return
            try:
                path.rmdir()
            except FileNotFoundError:
                return
            except NotADirectoryError:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
            return
        try:
            os.rmdir(name, dir_fd=self.descriptor)
        except FileNotFoundError:
            return
        except NotADirectoryError:
            try:
                details = os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISDIR(details.st_mode):
                raise
            os.unlink(name, dir_fd=self.descriptor)

    def assert_pinned(self) -> None:
        """Reject a replaced path before invoking a pathname-based child process."""
        if os.name == "nt":
            return
        expected = os.fstat(self.descriptor)
        try:
            current = os.stat(self.path, follow_symlinks=False)
        except OSError as exc:
            raise OSError(
                f"Temporary workspace path was replaced: {self.path}"
            ) from exc
        if _identity(current) != _identity(expected):
            raise OSError(f"Temporary workspace path was replaced: {self.path}")

    def current_path(self) -> Path:
        """Return the pinned directory's current name for published artifact URLs."""
        if os.name == "nt":
            return self.path
        expected = os.fstat(self.descriptor)
        try:
            current = os.stat(self.path, follow_symlinks=False)
        except OSError:
            current = None
        if current is not None and _identity(current) == _identity(expected):
            return self.path
        if platform.system() == "Darwin":
            import fcntl

            mac_value = fcntl.fcntl(
                self.descriptor, cast(Any, fcntl).F_GETPATH, bytearray(1024)
            )
            return Path(os.fsdecode(mac_value).rstrip("\0"))
        proc_value = os.readlink(f"/proc/self/fd/{self.descriptor}")
        if proc_value.endswith(" (deleted)"):
            proc_value = proc_value[: -len(" (deleted)")]
        return Path(proc_value)

    def cleanup(self) -> None:
        if os.name == "nt":
            shutil.rmtree(self.path)
            return
        _remove_directory_tree(self.descriptor)


def _remove_directory_tree(descriptor: int) -> None:
    """Remove private contents without following links or consulting their paths."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with os.scandir(descriptor) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                child = os.open(entry.name, flags, dir_fd=descriptor)
                try:
                    _remove_directory_tree(child)
                finally:
                    os.close(child)
                os.rmdir(entry.name, dir_fd=descriptor)
            else:
                os.unlink(entry.name, dir_fd=descriptor)


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
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    return windows, kernel, wintypes


def _open_windows_resource(
    path: Path, *, directory: bool, write: bool, replace: bool
) -> int:
    """Pin every Windows path component, rejecting links and reparse points."""
    import msvcrt

    windows, kernel, _ = _windows_api()

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
            attributes = FILE_FLAG_OPEN_REPARSE_POINT | (
                FILE_FLAG_BACKUP_SEMANTICS if is_directory else 0
            )
            if is_directory:
                access = FILE_READ_ATTRIBUTES
            else:
                access = GENERIC_WRITE if write else GENERIC_READ
            creation = (
                CREATE_NEW
                if write and not replace and index == len(components) - 1
                else OPEN_EXISTING
            )
            handle = kernel.CreateFileW(
                str(component),
                access,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                creation,
                attributes,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                raise windows.WinError(windows.get_last_error())
            handles.append(handle)
            info = WindowsFileAttributes()
            if not kernel.GetFileInformationByHandleEx(
                handle,
                FILE_ATTRIBUTE_TAG_INFO,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                raise windows.WinError(windows.get_last_error())
            if info.attributes & FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError(f"Refusing resource reparse point: {component}")
            if is_directory and not info.attributes & FILE_ATTRIBUTE_DIRECTORY:
                raise OSError(f"Resource directory is not a directory: {component}")
            if not is_directory and (
                info.attributes & FILE_ATTRIBUTE_DIRECTORY
                or kernel.GetFileType(handle) != FILE_TYPE_DISK
            ):
                raise OSError(f"Resource is not a regular file: {component}")
        mode = os.O_WRONLY if write else os.O_RDONLY
        descriptor: int = msvcrt.open_osfhandle(  # type: ignore[attr-defined]
            handles[-1], mode | getattr(os, "O_BINARY", 0)
        )
        handles.pop()
        return descriptor
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def open_windows_resource(path: Path, *, directory: bool) -> int:
    """Open a regular file or directory without following reparse points."""
    return _open_windows_resource(path, directory=directory, write=False, replace=False)


def open_windows_writable(path: Path, *, replace: bool) -> int:
    """Open a regular file for GENERIC_WRITE without following reparse points."""
    return _open_windows_resource(path, directory=False, write=True, replace=replace)


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


def _publish(
    source: PinnedDirectory, destination: Path, parent: int, overwrite: bool
) -> None:
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
        original_descriptor = source.open_regular("document.docx")
        try:
            file_descriptor = os.open(
                "document.docx",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=staging,
            )
        except BaseException:
            os.close(original_descriptor)
            raise
        with (
            os.fdopen(file_descriptor, "wb") as target,
            os.fdopen(original_descriptor, "rb") as original,
        ):
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


def _system_temporary_root() -> Path:
    """Select the OS temp namespace without consulting process environment."""
    return Path("/private") / "tmp" if sys.platform == "darwin" else Path("/") / "tmp"


def _writer_temporary_descriptor() -> int:
    """Pin a stable OS namespace rather than an arbitrary TMPDIR pathname."""
    # verified ownership and sticky permissions below
    root = _system_temporary_root()
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
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _writer_temporary_root() -> Path:
    """Return the verified temporary root for callers that only need its name."""
    descriptor = _writer_temporary_descriptor()
    os.close(descriptor)
    return _system_temporary_root()


@contextlib.contextmanager
def pinned_directory(path: Path) -> Iterator[PinnedDirectory]:
    """Open/create a publication directory and retain its identity."""
    if os.name == "nt":
        with _windows_directory_pin(path):
            descriptor = open_windows_resource(path, directory=True)
            try:
                yield PinnedDirectory(path.absolute(), descriptor)
            finally:
                os.close(descriptor)
        return
    descriptor = _open_parent(path)
    try:
        details = os.fstat(descriptor)
        if details.st_uid != os.geteuid() or details.st_mode & (
            stat.S_IWGRP | stat.S_IWOTH
        ):
            raise OSError(
                "Preview directory must be owned by the current user and not "
                "group/other writable"
            )
        yield PinnedDirectory(path.absolute(), descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def secure_temporary_directory(
    prefix: str, *, directory: Path | None = None
) -> Iterator[PinnedDirectory]:
    """Create a private workspace in a pinned, attacker-independent namespace."""
    if os.name == "nt":
        if directory is None:
            raise OSError("A pinned Windows temporary directory is required")
        with _windows_directory_pin(directory):
            parent_descriptor = open_windows_resource(directory, directory=True)
            temporary: Path | None = None
            windows_descriptor: int | None = None
            verified = False
            try:
                parent_identity = _identity(os.fstat(parent_descriptor))
                temporary = Path(tempfile.mkdtemp(prefix=prefix, dir=directory))
                if _identity(os.stat(temporary.parent)) != parent_identity:
                    raise OSError("Windows workspace parent identity changed")
                expected = _identity(os.stat(temporary))
                windows_descriptor = open_windows_resource(temporary, directory=True)
                if _identity(os.fstat(windows_descriptor)) != expected:
                    raise OSError("Windows workspace identity changed after mkdtemp")
                verified = True
                canary_name = f".workspace-canary-{uuid.uuid4().hex}"
                canary_value = uuid.uuid4().hex.encode("ascii")
                canary_descriptor = os.open(
                    temporary / canary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                try:
                    try:
                        canary_stream = os.fdopen(canary_descriptor, "wb")
                    except BaseException:
                        os.close(canary_descriptor)
                        raise
                    with canary_stream:
                        canary_identity = _identity(os.fstat(canary_descriptor))
                        canary_stream.write(canary_value)
                    check_descriptor = open_windows_resource(
                        temporary / canary_name, directory=False
                    )
                    try:
                        if _identity(os.fstat(check_descriptor)) != canary_identity:
                            raise OSError("Windows workspace canary identity changed")
                        contents = bytearray()
                        while chunk := os.read(check_descriptor, 4096):
                            contents.extend(chunk)
                        if bytes(contents) != canary_value:
                            raise OSError(
                                "Windows workspace canary verification failed"
                            )
                    finally:
                        os.close(check_descriptor)
                    if _identity(os.fstat(windows_descriptor)) != expected:
                        raise OSError(
                            "Windows workspace identity changed during canary"
                        )
                finally:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(temporary / canary_name)
                yield PinnedDirectory(temporary, windows_descriptor)
            finally:
                try:
                    if windows_descriptor is not None:
                        os.close(windows_descriptor)
                finally:
                    try:
                        if temporary is not None:
                            if verified:
                                with contextlib.suppress(FileNotFoundError):
                                    shutil.rmtree(temporary)
                            else:
                                with contextlib.suppress(OSError):
                                    temporary.rmdir()
                    finally:
                        os.close(parent_descriptor)
        return

    root = _system_temporary_root()
    parent = _writer_temporary_descriptor()
    name = f"{prefix}{uuid.uuid4().hex}"
    descriptor: int | None = None
    created = False
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent)
        created = True
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent,
        )
        details = os.fstat(descriptor)
        if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) & 0o077:
            raise OSError("Temporary workspace is not private")
        yield PinnedDirectory(root / name, descriptor)
    finally:
        try:
            if descriptor is not None:
                try:
                    _remove_directory_tree(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            try:
                if created:
                    workspace = PinnedDirectory(root / name, parent)
                    workspace.remove_entry(name)
            finally:
                os.close(parent)


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
        with secure_temporary_directory(prefix="markdown2docx-") as workspace:
            source = workspace.path / "document.docx"
            workspace.assert_pinned()
            yield source
            workspace.assert_pinned()
            _publish(workspace, destination, parent, overwrite)
    finally:
        os.close(parent)


def _open_windows_directory_handle(path: Path) -> int:
    """Open one directory without delete sharing and reject every reparse tag."""
    windows, kernel, _ = _windows_api()
    handle = kernel.CreateFileW(
        str(path),
        FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        raise windows.WinError(windows.get_last_error())
    handle = cast(int, handle)
    info = WindowsFileAttributes()
    if not kernel.GetFileInformationByHandleEx(
        handle,
        FILE_ATTRIBUTE_TAG_INFO,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        kernel.CloseHandle(handle)
        raise windows.WinError(windows.get_last_error())
    if (
        info.attributes & FILE_ATTRIBUTE_REPARSE_POINT
        or not info.attributes & FILE_ATTRIBUTE_DIRECTORY
    ):
        kernel.CloseHandle(handle)
        raise OSError(f"Refusing unsafe output directory/reparse point: {path}")
    return handle


def _mkdir_if_missing(path: Path) -> None:
    """Create a directory idempotently under concurrent callers."""
    if path.exists():
        return
    try:
        path.mkdir()
    except FileExistsError:
        pass


@contextlib.contextmanager
def _windows_directory_pin(path: Path) -> Iterator[None]:
    """Retain every Windows ancestor so pathname-based child tools stay pinned."""
    handles: list[int] = []
    try:
        for ancestor in reversed([path.absolute(), *path.absolute().parents]):
            _mkdir_if_missing(ancestor)
            handles.append(_open_windows_directory_handle(ancestor))
        yield
    finally:
        for handle in reversed(handles):
            _windows_api()[1].CloseHandle(handle)


@contextlib.contextmanager
def _windows_output(destination: Path, *, overwrite: bool) -> Iterator[Path]:
    """Pin Windows directory handles without delete sharing; reject reparse points.

    Omitting FILE_SHARE_DELETE prevents ancestors from being renamed/replaced
    while path-based writing and publication are in progress.
    """
    absolute = destination.absolute()
    with _windows_directory_pin(absolute.parent):
        if absolute.is_symlink():
            raise OSError("Refusing symlink output path")
        if absolute.exists() and (not overwrite or not absolute.is_file()):
            raise FileExistsError(f"Output file already exists: {absolute}")
        with tempfile.TemporaryDirectory(
            prefix=".markdown2docx-", dir=absolute.parent
        ) as temporary:
            handle = _open_windows_directory_handle(Path(temporary))
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
                _windows_api()[1].CloseHandle(handle)
