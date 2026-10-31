"""The fixture repository: a small repository every source test indexes, and the builders for the
hostile variants the fake GitHub serves. Nothing here touches the network.

`INDEXED_PATHS` are the files that become documents; every other file is one the index must skip
(a skipped directory, a skipped suffix, a binary, bytes that are not UTF-8, a file over the size
cap).
"""

import io
import tarfile
from collections.abc import Callable, Mapping
from typing import Final

FIXTURE_COMMIT: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"
FIXTURE_ROOT: Final = "octocat-Hello-World-7fd1a60"

PYTHON_SOURCE: Final = '''"""Greeting helpers."""

import os


class Greeter:
    def __init__(self, name):
        self.name = name

    def greet(self):
        return f"Hello, {self.name}"


def shout(text):
    return text.upper()


def decorator(fn):
    return fn


@decorator
def main():
    print(Greeter(os.getcwd()).greet())
'''

JAVASCRIPT_SOURCE: Final = """import { shout } from "./app.js";

export function add(a, b) {
  return a + b;
}

const double = (x) => x * 2;

class Counter {
  constructor() {
    this.n = 0;
  }
  inc() {
    this.n += 1;
  }
}

module.exports = { add, double, Counter, shout };
"""

TYPESCRIPT_SOURCE: Final = """export interface Point {
  x: number;
  y: number;
}

export type Id = string | number;

export function norm(p: Point): number {
  return Math.hypot(p.x, p.y);
}

export class Box<T> {
  constructor(public value: T) {}
}

enum Color {
  Red,
  Green,
}
"""

TSX_SOURCE: Final = """import React from "react";

export function Hello({ name }: { name: string }) {
  return <h1>Hello {name}</h1>;
}

export const Bye = () => <p>Bye</p>;
"""

# 297 comment lines, a blank one, then a definition on lines 299 to 300: past 256, where
# tree-sitter's `Point.row` and `Point.column` corrupt memory (the review's P0). Every other
# fixture file is short.
LATE_SOURCE: Final = "".join(f"# filler line {n}\n" for n in range(1, 298)) + (
    "\ndef last_one():\n    return 300\n"
)

FIXTURE_FILES: Final[Mapping[str, bytes]] = {
    "src/late.py": LATE_SOURCE.encode(),
    "README.md": b"# Hello World\n\nA fixture repository for the source tests.\n",
    "src/app.py": PYTHON_SOURCE.encode(),
    "src/util.js": JAVASCRIPT_SOURCE.encode(),
    "src/types.ts": TYPESCRIPT_SOURCE.encode(),
    "src/widget.tsx": TSX_SOURCE.encode(),
    "docs/guide.txt": b"Install it.\n\nRun it.\n\nStop it.\n",
    # Skipped: a skipped directory, a skipped suffix, a binary, bytes that are not UTF-8, and a
    # file over the 1 MiB cap.
    "node_modules/dep/index.js": b"module.exports = 1;\n",
    "assets/logo.png": b"\x89PNG\r\n\x1a\n" + bytes(range(256)),
    "data/blob.dat": b"head\x00tail\n",
    "data/latin1.txt": b"caf\xe9\n",
    "data/big.txt": b"x" * (1024 * 1024 + 1),
}

INDEXED_PATHS: Final = frozenset(
    {
        "README.md",
        "src/app.py",
        "src/util.js",
        "src/types.ts",
        "src/widget.tsx",
        "src/late.py",
        "docs/guide.txt",
    }
)


def build_tarball(
    files: Mapping[str, bytes],
    *,
    extra: Callable[[tarfile.TarFile], None] | None = None,
    root: str = FIXTURE_ROOT,
) -> bytes:
    """A gzip tarball laid out as GitHub's: a global pax header, the root directory, then every
    file under it. `extra` adds members of any kind (links, devices, hostile names)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        tar.pax_headers = {"comment": FIXTURE_COMMIT}
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        tar.addfile(directory)
        for path, data in files.items():
            info = tarfile.TarInfo(f"{root}/{path}")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
        if extra is not None:
            extra(tar)
    return buffer.getvalue()


def add_member(
    tar: tarfile.TarFile,
    name: str,
    *,
    kind: bytes = tarfile.REGTYPE,
    data: bytes = b"",
    link: str = "",
) -> None:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    info.linkname = link
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def fixture_tarball() -> bytes:
    return build_tarball(FIXTURE_FILES)


def links_tarball() -> bytes:
    """A symlink, a hard link, a device and a fifo beside one honest file; none may be stored."""

    def extra(tar: tarfile.TarFile) -> None:
        add_member(tar, f"{FIXTURE_ROOT}/link.txt", kind=tarfile.SYMTYPE, link="/etc/passwd")
        add_member(
            tar, f"{FIXTURE_ROOT}/hard.txt", kind=tarfile.LNKTYPE, link=f"{FIXTURE_ROOT}/ok.txt"
        )
        add_member(tar, f"{FIXTURE_ROOT}/device", kind=tarfile.CHRTYPE)
        add_member(tar, f"{FIXTURE_ROOT}/pipe", kind=tarfile.FIFOTYPE)

    return build_tarball({"ok.txt": b"an honest file\n"}, extra=extra)


def traversal_tarball() -> bytes:
    """Members named to escape the root; none may be stored. One honest file stays."""

    def extra(tar: tarfile.TarFile) -> None:
        for name in (
            f"{FIXTURE_ROOT}/../evil.txt",
            "../../evil.txt",
            "/abs/evil.txt",
            f"{FIXTURE_ROOT}/a/../../evil.txt",
            f"{FIXTURE_ROOT}\\evil.txt",
            f"{FIXTURE_ROOT}/dir\\..\\evil.txt",
        ):
            add_member(tar, name, data=b"evil\n")

    return build_tarball({"ok.txt": b"an honest file\n"}, extra=extra)


def bomb_tarball(skipped_bytes: int) -> bytes:
    """One honest file and a skipped-directory member of `skipped_bytes` zeros: it decompresses
    in full even though nothing is stored."""

    def extra(tar: tarfile.TarFile) -> None:
        add_member(tar, f"{FIXTURE_ROOT}/node_modules/big.bin", data=bytes(skipped_bytes))

    return build_tarball({"ok.txt": b"an honest file\n"}, extra=extra)


def empty_members_tarball(count: int) -> bytes:
    """`count` empty files under the root: a few bytes of gzip each, and nothing to store."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        directory = tarfile.TarInfo(FIXTURE_ROOT)
        directory.type = tarfile.DIRTYPE
        tar.addfile(directory)
        for n in range(count):
            tar.addfile(tarfile.TarInfo(f"{FIXTURE_ROOT}/e{n}"))
    return buffer.getvalue()


def crafted_tarball() -> bytes:
    """An honest Python file and a TypeScript file crafted to make tree-sitter's time grow with
    the square of its size (`"'` repeated): parsed in the API process it would stall the server."""
    return build_tarball({"ok.py": PYTHON_SOURCE.encode(), "bad.ts": b"\"'" * 40_000})


def many_tarball(count: int, size: int = 100) -> bytes:
    return build_tarball({f"f{i}.txt": b"line\n" * (size // 5) for i in range(count)})
