from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from . import _core
from .document import Document
from .errors import _native_errors
from .limits import Limits
from .models import BuildInfo, Inspection, ProbeResult, _decode

PathLike = str | os.PathLike[str]


def _limits(limits: Limits | None) -> dict[str, Any]:
    return asdict(limits if limits is not None else Limits.desktop())


def _bytes(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise TypeError("expected immutable bytes; use a *_file function for paths")
    return data


def build_info() -> BuildInfo:
    return _decode(BuildInfo, _core.build_info())


def probe(data: bytes, *, limits: Limits | None = None) -> ProbeResult:
    with _native_errors():
        return _decode(
            ProbeResult, _core.probe_bytes(_bytes(data), json.dumps(_limits(limits)))
        )


def probe_file(path: PathLike, *, limits: Limits | None = None) -> ProbeResult:
    with _native_errors():
        return _decode(
            ProbeResult, _core.probe_path(os.fspath(path), json.dumps(_limits(limits)))
        )


def inspect(
    data: bytes, *, filename: str | None = None, limits: Limits | None = None
) -> Inspection:
    options = json.dumps({"limits": _limits(limits), "filename": filename})
    with _native_errors():
        return _decode(Inspection, _core.inspect_bytes(_bytes(data), options))


def inspect_file(path: PathLike, *, limits: Limits | None = None) -> Inspection:
    options = json.dumps({"limits": _limits(limits), "filename": os.fspath(path)})
    with _native_errors():
        return _decode(Inspection, _core.inspect_path(os.fspath(path), options))


def read(
    data: bytes,
    *,
    filename: str | None = None,
    limits: Limits | None = None,
    read_metadata: bool = True,
    verify_all: bool = False,
) -> Document:
    options = json.dumps(
        {
            "limits": _limits(limits),
            "filename": filename,
            "read_metadata": read_metadata,
            "verify_all": verify_all,
        }
    )
    with _native_errors():
        return Document(_core.read_bytes(_bytes(data), options))


def read_file(
    path: PathLike,
    *,
    limits: Limits | None = None,
    read_metadata: bool = True,
    verify_all: bool = False,
) -> Document:
    options = json.dumps(
        {
            "limits": _limits(limits),
            "filename": os.fspath(path),
            "read_metadata": read_metadata,
            "verify_all": verify_all,
        }
    )
    with _native_errors():
        return Document(_core.read_path(os.fspath(path), options))
