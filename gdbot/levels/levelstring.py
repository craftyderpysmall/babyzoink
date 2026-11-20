"""Build and parse GD inner strings and protocol-v0 level data.

The header and numeric object keys follow the gd.docs format references
listed in levels/drills/README.md.
"""

import base64
import gzip
import io
import math
import zlib
from dataclasses import dataclass, field

MAX_ENCODED_LEVEL = 16 * 1024 * 1024
MAX_INNER_LEVEL = 64 * 1024 * 1024
MAX_LEVEL_RECORDS = 500_000


def decode_level_bytes(data: str, *, legacy: bool = False) -> bytes:
    """Expand a level within byte and record limits. Legacy download formats opt in."""
    if not isinstance(data, str) or not data or len(data) > MAX_ENCODED_LEVEL:
        raise ValueError("level data exceeds the encoded size limit or is empty or invalid")
    if legacy and (data.startswith("k") or ";" in data):
        raw = data.encode("utf-8")
    else:
        try:
            compressed = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
            if legacy and not compressed.startswith(b"\x1f\x8b"):
                decoder = zlib.decompressobj()
                raw = decoder.decompress(compressed, MAX_INNER_LEVEL + 1)
                if len(raw) <= MAX_INNER_LEVEL and not decoder.eof:
                    raise ValueError("incomplete zlib level data")
            else:
                with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
                    raw = archive.read(MAX_INNER_LEVEL + 1)
        except (OSError, EOFError, zlib.error) as error:
            raise ValueError("invalid compressed level data") from error
    if len(raw) > MAX_INNER_LEVEL:
        raise ValueError("level data exceeds the decoded size limit")
    if raw.count(b";") > MAX_LEVEL_RECORDS:
        raise ValueError("level data exceeds the record limit")
    return raw


# No explicit color channels: use the game's defaults.
CLASSIC_CUBE = {
    "kA2": "0", "kA3": "0", "kA4": "0", "kA8": "0", "kA9": "0",
    "kA10": "0", "kA11": "0", "kA22": "0",
}


def _number(value: int | float) -> str:
    if not math.isfinite(value):
        raise ValueError("level values must be finite")
    return str(value)


def _record(properties: dict[str, str]) -> str:
    for key, value in properties.items():
        if not key or any(char in key or char in value for char in ",;\r\n"):
            raise ValueError("invalid key or delimiter in a level property")
    return ",".join(part for pair in properties.items() for part in pair)


def _parse_record(record: str) -> dict[str, str]:
    tokens = record.split(",")
    if len(tokens) % 2 or not record:
        raise ValueError("expected key/value pairs")
    properties = dict(zip(tokens[::2], tokens[1::2]))
    if "" in properties or len(properties) * 2 != len(tokens):
        raise ValueError("empty or duplicate property key")
    _record(properties)
    return properties


@dataclass
class LevelString:
    header: dict[str, str] = field(default_factory=CLASSIC_CUBE.copy)
    objects: list[dict[str, str]] = field(default_factory=list)

    def add(
        self, object_id: int, x: int | float, y: int | float, *,
        rotation: int | float = 0, flip_x: bool = False, flip_y: bool = False,
        scale: int | float = 1, properties: dict[int, int | float | str] | None = None,
    ) -> None:
        if type(object_id) is not int or object_id <= 0 or scale <= 0:
            raise ValueError("object id and scale must be positive")
        obj = {"1": str(object_id), "2": _number(x), "3": _number(y)}
        for key, value, default in (
            ("6", rotation, 0), ("4", int(flip_x), 0), ("5", int(flip_y), 0), ("32", scale, 1),
        ):
            if value != default:
                obj[key] = _number(value)
        for key, value in sorted((properties or {}).items()):
            if type(key) is not int or key < 1 or key in (1, 2, 3, 4, 5, 6, 32):
                raise ValueError("use the named arguments for standard object properties")
            obj[str(key)] = value if isinstance(value, str) else _number(value)
        _record(obj)
        self.objects.append(obj)

    def inner(self) -> str:
        return ";".join((_record(self.header), *map(_record, self.objects))) + ";"

    def encode(self) -> str:
        """Return padded URL-safe base64 of a gzip stream with a fixed timestamp."""
        output = io.BytesIO()
        with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as archive:
            archive.write(self.inner().encode("utf-8"))
        return base64.urlsafe_b64encode(output.getvalue()).decode("ascii")

    @classmethod
    def parse(cls, inner: str):
        header, *records = inner.removesuffix(";").split(";")
        objects = []
        for record in records:
            properties = _parse_record(record)
            if not {"1", "2", "3"} <= properties.keys():
                raise ValueError("object must have an id and x/y coordinates")
            objects.append(properties)
        return cls(_parse_record(header), objects)

    @classmethod
    def decode(cls, data: str):
        return cls.parse(decode_level_bytes(data).decode("utf-8"))


START_POSITION = 31
START_MODES = ("cube", "ship", "ball", "ufo", "wave", "robot", "spider", "swing")


def with_startpos(level: LevelString, x: float, mode: str, speed: int, gravity: bool, mini: bool) -> LevelString:
    """Return an independent floor-start variant. Speed uses GD's 0=normal, 1=slow, 2–4=fast codes.

    Wire format: https://github.com/nekitdev/gd.py/blob/main/gd/api/objects.py#L632-L714
    Callers must verify that the skipped prefix has no required trigger state.
    """
    if x < 0 or mode not in START_MODES or type(speed) is not int or speed not in range(5):
        raise ValueError("invalid start position, mode, or speed code")
    if type(gravity) is not bool or type(mini) is not bool:
        raise ValueError("gravity and mini must be booleans")
    if any(obj["1"] == str(START_POSITION) for obj in level.objects):
        raise ValueError("level already contains a start position")
    result = LevelString(level.header.copy(), [obj.copy() for obj in level.objects])
    result.objects.append({
        "1": str(START_POSITION), "2": _number(x), "3": "15",
        "kA2": str(START_MODES.index(mode)), "kA3": str(int(mini)), "kA4": str(speed),
        "kA8": "0", "kA9": "1", "kA11": str(int(gravity)),
    })
    return result
