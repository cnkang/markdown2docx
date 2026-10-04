#!/usr/bin/env python3
"""Install Pandoc 3.12 from checksum-pinned official release archives."""

import argparse
import hashlib
import os
import platform
import shutil
import tempfile
import urllib.request
from pathlib import Path

# GitHub's official 3.12 release asset digests, verified 2026-10-04.
ASSETS = {
    "pandoc-3.12-windows-x86_64.zip": "2a77ebc2517d13e95056e76b1cd5b574cfe958ac61aa6058117d80c22ca19b79",
    "pandoc-3.12-arm64-macOS.zip": "f148ca09c9f36594db527a9fc988ad736290ce428f79594c50208cd1ec58b3c0",
    "pandoc-3.12-x86_64-macOS.zip": "18577f9460c3dc5d2651ad3bab37d513bc2034a5a777fbe18fa0a5acf2e936ea",
    "pandoc-3.12-linux-amd64.tar.gz": "67d7d011fed8c8543306022b985b9b2499ab9b74818df91d8727c7e9ebc5ba06",
    "pandoc-3.12-linux-arm64.tar.gz": "6cefcf7100e23a99447c26f89d1ff5b253f3407fcef99a9e27ae06f3ed16cb82",
}


def download_checked(url: str, destination: Path, checksum: str) -> None:
    if not url.startswith("https://github.com/jgm/pandoc/releases/download/3.12/"):
        raise ValueError("Unexpected Pandoc asset origin")
    digest = hashlib.sha256()
    size = 0
    with (
        # Fixed official HTTPS release path; checksum verified before extraction.
        urllib.request.urlopen(url, timeout=60) as response,  # nosec B310
        destination.open("wb") as stream,
    ):
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                raise ValueError("Pandoc archive exceeds 100 MiB")
            digest.update(chunk)
            stream.write(chunk)
    if digest.hexdigest() != checksum:
        raise ValueError("Pandoc archive SHA-256 mismatch; refusing extraction")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(".tools"))
    parser.add_argument("--github-env", action="store_true")
    args = parser.parse_args()
    system, machine = platform.system(), platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
    asset = {
        "Windows": "pandoc-3.12-windows-x86_64.zip",
        "Darwin": f"pandoc-3.12-{'arm64' if architecture == 'arm64' else 'x86_64'}-macOS.zip",
        "Linux": f"pandoc-3.12-linux-{architecture}.tar.gz",
    }[system]
    destination = args.output_dir.absolute()
    destination.mkdir(parents=True, exist_ok=True)
    executable = "pandoc.exe" if os.name == "nt" else "pandoc"
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        root = Path(temporary)
        archive = root / asset
        download_checked(
            f"https://github.com/jgm/pandoc/releases/download/3.12/{asset}",
            archive,
            ASSETS[asset],
        )
        extracted = root / "extracted"
        shutil.unpack_archive(archive, extracted)
        candidates = [path for path in extracted.rglob(executable) if path.is_file()]
        if len(candidates) != 1:
            raise ValueError("Expected exactly one Pandoc executable")
        binary = destination / executable
        candidates[0].chmod(0o755)
        os.replace(candidates[0], binary)
    if args.github_env:
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
            stream.write(f"PYPANDOC_PANDOC={binary}\n")
    print(binary)


if __name__ == "__main__":
    main()
