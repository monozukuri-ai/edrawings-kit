from collections.abc import Iterator
from contextlib import contextmanager

from . import _core
from .models import Diagnostic, _decode


class EdrawingsError(Exception):
    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic
        self.code = diagnostic.code
        self.stage = diagnostic.stage
        super().__init__(f"{self.code}: {diagnostic.message}")


class InvalidFormatError(EdrawingsError):
    pass


class UnsupportedFeatureError(EdrawingsError):
    pass


class LimitExceededError(EdrawingsError):
    pass


@contextmanager
def _native_errors() -> Iterator[None]:
    try:
        yield
    except _core.NativeError as error:
        diagnostic = _decode(Diagnostic, str(error))
        cls = {
            "invalid": InvalidFormatError,
            "unsupported": UnsupportedFeatureError,
            "limit_exceeded": LimitExceededError,
        }.get(diagnostic.classification, EdrawingsError)
        raise cls(diagnostic) from None
