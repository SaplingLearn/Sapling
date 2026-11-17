"""Bounds on what an uploaded zip (an .apkg, .docx, .pptx, .xlsx) may expand to.

Every one of those formats is a zip, and every parser we hand them to
(``zipfile``, mammoth, python-pptx, openpyxl) inflates members without a size
limit of its own. A few MB of upload can name gigabytes of deflated zeros, so
the central directory is checked BEFORE any parser runs: the declared
uncompressed sizes are summed and the entry count is capped.

The declared size is a bound worth trusting: ``zipfile`` stops a member's
stream at its declared ``file_size`` (and fails its CRC past it), so no reader
built on ``zipfile`` ever inflates more than this check admitted.
"""
from __future__ import annotations

import io
import zipfile

#: Default ceiling on the uncompressed total of one archive. A dense lecture
#: deck with images expands to tens of MB; 200 MB is far past any real file.
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
#: Default ceiling on members. A big Office file or Anki deck with media has
#: a few thousand; past this the central directory itself is the attack.
MAX_ENTRIES = 10_000


class ArchiveTooLarge(ValueError):
    """The archive would expand past a bound. A ValueError so the parsers'
    existing "bad file" handling answers it as a 4xx, not a 500."""


def check_zip_bounds(
    source: bytes | zipfile.ZipFile,
    *,
    max_uncompressed: int = MAX_UNCOMPRESSED_BYTES,
    max_entries: int = MAX_ENTRIES,
) -> None:
    """Raise :class:`ArchiveTooLarge` when ``source`` has more than
    ``max_entries`` members or their declared sizes sum past
    ``max_uncompressed``. Bytes that are not a zip at all pass: the caller's
    own parser reports that in its own words."""
    if isinstance(source, zipfile.ZipFile):
        _check(source, max_uncompressed, max_entries)
        return
    try:
        zf = zipfile.ZipFile(io.BytesIO(source))
    except (zipfile.BadZipFile, ValueError, OSError):
        return
    with zf:
        _check(zf, max_uncompressed, max_entries)


def _check(zf: zipfile.ZipFile, max_uncompressed: int, max_entries: int) -> None:
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ArchiveTooLarge(f"The file has too many parts (over {max_entries}).")
    total = 0
    for info in infos:
        total += max(0, info.file_size)
        if total > max_uncompressed:
            raise ArchiveTooLarge(
                f"The file expands to more than {max_uncompressed // (1024 * 1024)} MB."
            )
