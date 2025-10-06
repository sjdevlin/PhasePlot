"""
movie2tiff.py – Proprietary “TemI” movie → TIFF converter
=========================================================

A faithful Python rewrite of *movie2tiff_v2.c* that understands the bespoke
“TemI” movie container produced by the original camera software.  It extracts
**the first frame only**, writes it as a single‑page TIFF with **loss‑less
compression** (LZW by default) **and embeds all original header fields as JSON
metadata** so nothing is lost.

Dependencies
------------
* **NumPy**
* **Pillow ≥ 8.0** (for TIFF writing). The code now works on *any* Pillow 8→10
  release – no `TAGS_V2` attribute required.

Usage
-----
```python
from movie2tiff import Movie2Tiff

conv = Movie2Tiff()                           # LZW compression
conv.convert('capture.temi', 'frame0.tif')    # → frame0.tif
```
You can choose another loss‑less scheme (`"tiff_adobe_deflate"`, `"tiff_zip"`,
or `"raw"` for none):
```python
conv = Movie2Tiff(compression='tiff_zip')
```
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import numpy as np
from PIL import Image, TiffImagePlugin

# ---------------------------------------------------------------------------
# Constants mirroring those in movie2tiff_v2.c
# ---------------------------------------------------------------------------
CAMERA_MOVIE_MAGIC = 0x496D6554  # ASCII “TemI” little‑endian
CAMERA_HEADER_LEN = 56  # bytes

# Pixel‑format enums from the original header
CAMERA_PIXELFORMAT_MONO_8 = 0x01080001
CAMERA_PIXELFORMAT_MONO_12_PACKED = 0x010C0006
CAMERA_PIXELFORMAT_MONO_16 = 0x01100007
CAMERA_PIXELFORMAT_MONO_32 = 0x01200111

G_BIG_ENDIAN = 4321
G_LITTLE_ENDIAN = 1234

_LOSSLESS_TIFF = {"raw", "tiff_lzw", "tiff_zip", "tiff_adobe_deflate"}

# TIFF tag numbers we use (numeric so they work on all Pillow versions)
TAG_IMAGE_DESCRIPTION = 270  # ASCII or UTF‑8 string
TAG_DATETIME = 306           # "YYYY:MM:DD HH:MM:SS"


# ---------------------------------------------------------------------------
# Header helper – exactly matches `camera_save_struct` (version ≥ 2)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class FrameHeader:
    magic: int
    version: int
    type: int
    pixelformat: int
    length_header: int
    length_data: int
    endianness: int
    time_sec: int
    time_nsec: int
    width: int
    height: int
    stride: int

    _STRUCT = struct.Struct("<7I2Q3I")  # little‑endian layout from the C code

    @classmethod
    def from_bytes(cls, buf: bytes) -> "FrameHeader":
        if len(buf) < CAMERA_HEADER_LEN:
            raise ValueError("Buffer shorter than camera_save_struct")
        fields = cls._STRUCT.unpack_from(buf)
        hdr = cls(*fields)
        if hdr.magic != CAMERA_MOVIE_MAGIC:
            raise ValueError(
                f"Bad magic 0x{hdr.magic:08X}, expected 0x{CAMERA_MOVIE_MAGIC:08X}")
        return hdr

    # Convenience helpers --------------------------------------------------
    @property
    def shape(self) -> Tuple[int, int]:
        return self.height, self.width

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.time_sec + self.time_nsec / 1e9, tz=timezone.utc)

    def to_json(self, extra: bytes | None = None) -> str:
        """Return *all* header fields (+ extra bytes) as pretty‑printed JSON."""
        d = {
            "magic": f"0x{self.magic:08X}",
            "version": self.version,
            "type": self.type,
            "pixelformat": f"0x{self.pixelformat:08X}",
            "length_header": self.length_header,
            "length_data": self.length_data,
            "endianness": self.endianness,
            "time_sec": self.time_sec,
            "time_nsec": self.time_nsec,
            "width": self.width,
            "height": self.height,
            "stride": self.stride,
        }
        if extra:
            d["extra_header_hex"] = extra.hex()
        return json.dumps(d, indent=2)


# ---------------------------------------------------------------------------
# Main public class
# ---------------------------------------------------------------------------
class Movie2Tiff:
    """Convert the first frame of a proprietary “TemI” movie to TIFF."""

    def __init__(self, compression: str = "tiff_lzw") -> None:
        compression = compression.lower()
        if compression not in _LOSSLESS_TIFF:
            raise ValueError(
                f"Unsupported or lossy compression '{compression}'. "
                f"Choose from {', '.join(sorted(_LOSSLESS_TIFF))}.")
        self.compression = compression

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def convert(self, src: str | Path, dst: str | Path) -> Path:
        """Extract and write the first frame.

        Parameters
        ----------
        src : path‑like
            *TemI* movie file.
        dst : path‑like
            Output TIFF path (extension forced to .tif/.tiff).
        Returns
        -------
        pathlib.Path
            Absolute path of written file.
        """
        src_p = Path(src).expanduser().resolve()
        dst_p = Path(dst).expanduser().with_suffix(".tiff").resolve()

        with src_p.open("rb") as fh:
            hdr, extra, frame_mv = self._read_first_frame(fh)

        img_arr = self._decode_frame(hdr, frame_mv)
        self._save_tiff(img_arr, dst_p, hdr, extra)
        return dst_p

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _read_first_frame(fh) -> tuple[FrameHeader, bytes, memoryview]:
        """Scan for the first 'TemI' magic and return header + payload."""
        data = fh.read()
        magic = CAMERA_MOVIE_MAGIC.to_bytes(4, "little")
        idx = data.find(magic)
        if idx == -1:
            raise ValueError("Magic word 'TemI' not found – not a TemI movie file?")

        hdr_bytes = data[idx : idx + CAMERA_HEADER_LEN]
        header = FrameHeader.from_bytes(hdr_bytes)

        extra_start = idx + CAMERA_HEADER_LEN
        extra_end = idx + header.length_header
        extra_hdr = data[extra_start:extra_end]

        frame_start = extra_end
        frame_end = frame_start + header.length_data
        frame_mv = memoryview(data)[frame_start:frame_end]
        return header, extra_hdr, frame_mv

    @staticmethod
    def _decode_frame(header: FrameHeader, buf: memoryview) -> np.ndarray:
        """Return a numpy 2‑D array matching the pixel format."""
        h, w = header.shape
        stride = header.stride

        if header.pixelformat == CAMERA_PIXELFORMAT_MONO_8:
            out = np.empty((h, w), dtype=np.uint8)
            for r in range(h):
                off = r * stride
                out[r] = np.frombuffer(buf[off: off + w], dtype=np.uint8, count=w)
            return out

        if header.pixelformat == CAMERA_PIXELFORMAT_MONO_16:
            out = np.empty((h, w), dtype=np.uint16)
            for r in range(h):
                off = r * stride
                row = np.frombuffer(buf[off: off + w * 2], dtype="<u2", count=w)
                if header.endianness == G_BIG_ENDIAN:
                    row = row.byteswap()
                out[r] = row
            return out

        if header.pixelformat == CAMERA_PIXELFORMAT_MONO_12_PACKED:
            out = np.empty((h, w), dtype=np.uint16)
            for r in range(h):
                in_off = r * stride
                packed = buf[in_off: in_off + ((w + 1) // 2) * 3]
                j = 0
                for c in range(0, w, 2):
                    b0, b1, b2 = packed[j : j + 3]
                    out[r, c] = b0 | ((b1 & 0x0F) << 8)
                    if c + 1 < w:
                        out[r, c + 1] = (b1 >> 4) | (b2 << 4)
                    j += 3
            return out

        if header.pixelformat == CAMERA_PIXELFORMAT_MONO_32:
            out = np.empty((h, w), dtype=np.uint32)
            for r in range(h):
                off = r * stride
                row = np.frombuffer(buf[off: off + w * 4], dtype="<u4", count=w)
                if header.endianness == G_BIG_ENDIAN:
                    row = row.byteswap()
                out[r] = row
            return out

        raise NotImplementedError(
            f"Pixel format 0x{header.pixelformat:08X} not implemented.")

    def _save_tiff(
        self,
        arr: np.ndarray,
        path: Path,
        hdr: FrameHeader,
        extra: bytes,
    ) -> None:
        img = Image.fromarray(arr)

        # Build TIFF IFD (Image File Directory) – numeric tags so Pillow 8–10 works
        try:
            ifd = TiffImagePlugin.ImageFileDirectory_v2()
        except AttributeError:  # Pillow <9.1 fallback
            ifd = TiffImagePlugin.ImageFileDirectory()

        ifd[TAG_IMAGE_DESCRIPTION] = hdr.to_json(extra)
        ifd[TAG_DATETIME] = hdr.timestamp.strftime("%Y:%m:%d %H:%M:%S")

        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(
            str(path),
            format="TIFF",
            compression=None if self.compression == "raw" else self.compression,
            tiffinfo=ifd,
        )



# ---------------------------------------------------------------------------
# Optional CLI front‑end
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse, textwrap

    parser = argparse.ArgumentParser(
        description="Extract the first frame of a TemI movie into a TIFF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Supported loss‑less compression names:
              • raw                (no compression)
              • tiff_lzw           (default)
              • tiff_zip
              • tiff_adobe_deflate
        """),
    )
    parser.add_argument("src", help="Path to .temi movie file")
    parser.add_argument("dst", help="Output .tif/.tiff path")
    parser.add_argument("-c", "--compression", default="tiff_lzw",
                        help="TIFF compression (loss‑less only)")
    args = parser.parse_args()

    conv = Movie2Tiff(compression=args.compression)
    out_path = conv.convert(args.src, args.dst)
    print(f"✔ Wrote {out_path}")
