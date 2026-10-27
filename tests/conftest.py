import io
import warnings
import zipfile

import pytest

HSF = b";; HSF V19.10 \nI\x04\0\0\0"
PREFIX = b"[\x01\0\0\0\xbe\r2008+ archive" + bytes(68) + bytes([255, 255, 255, 127])


def make_zip(
    entries=None, *, prefix=False, method=zipfile.ZIP_DEFLATED, descriptor=False
):
    class Stream(io.BytesIO):
        def seek(self, *args):
            raise OSError("unseekable")

    output = Stream() if descriptor else io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w", compression=method) as archive:
            for name, data in entries if entries is not None else [("eModel", HSF)]:
                archive.writestr(name, data)
    return (PREFIX if prefix else b"") + output.getvalue()


@pytest.fixture
def zip_factory():
    return make_zip
