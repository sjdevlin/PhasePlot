"""
movie2tiff.py  TemI movie → per-frame TIFF extractor with focus scoring
=================================================================        
Process **all** frames and return filenames + focus scores.

        Parameters
        ----------
        movie_name : path-like
            TemI movie file.
        file_stub : str or path-like or ``None``
            Base name for output files  if ``None`` or empty, the movie's
            *stem* is used.  For example, movie `clip.temi` → `clip_0001.tiff`,
            `clip_0002.tiff`, … or `clip_0001.png`, `clip_0002.png`, …

        Returns
        -------
        (list[Path], list[float], list[float])
            *Absolute* paths of written image files, their corresponding focus
            scores, and highest pixel values (same order).
        sion extracts **every frame** from a proprietary *TemI* movie, saves
each frame to an individual TIFF, and returns the filename list **plus a per-
frame focus score**.  Filenames are based on a *stub* that you supply (or the
movies own name if you leave it blank).

Focus score algorithm
---------------------
A simple, fast, no-dependency metric:
* **Variance of the Laplacian** high-frequency content indicates sharp focus.
  For an NxM grayscale image *I* the discrete Laplacian is approximated by

  $$ \nabla^2 I = -4I_{i,j} + I_{i-1,j}+I_{i+1,j}+I_{i,j-1}+I_{i,j+1} $$
  and the focus score is the population variance of that response.

No OpenCV/SciPy needed  implemented with NumPy slicing.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Tuple

import numpy as np
from PIL import Image, TiffImagePlugin
from PIL.PngImagePlugin import PngInfo

# ---------------------------------------------------------------------------
# TemI constants (from movie2tiff_v2.c)
# ---------------------------------------------------------------------------
CAMERA_MOVIE_MAGIC = 0x496D6554  # 'TemI' little-endian
CAMERA_HEADER_LEN = 56

CAMERA_PIXELFORMAT_MONO_8 = 0x01080001
CAMERA_PIXELFORMAT_MONO_12_PACKED = 0x010C0006
CAMERA_PIXELFORMAT_MONO_16 = 0x01100007
CAMERA_PIXELFORMAT_MONO_32 = 0x01200111

G_BIG_ENDIAN = 4321
G_LITTLE_ENDIAN = 1234

_LOSSLESS_TIFF = {"raw", "tiff_lzw", "tiff_zip", "tiff_adobe_deflate"}

TAG_IMAGE_DESCRIPTION = 270  # ASCII/UTF-8 – JSON header dump
TAG_DATETIME = 306           # "YYYY:MM:DD HH:MM:SS"


# ---------------------------------------------------------------------------
# Header helper – mirrors `camera_save_struct` (version ≥ 2)
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

    _STRUCT = struct.Struct("<7I2Q3I")

    @classmethod
    def from_bytes(cls, buf: bytes) -> "FrameHeader":
        if len(buf) < CAMERA_HEADER_LEN:
            raise ValueError("Incomplete camera_save_struct header")
        fields = cls._STRUCT.unpack_from(buf)
        hdr = cls(*fields)
        if hdr.magic != CAMERA_MOVIE_MAGIC:
            raise ValueError("Bad TemI magic")
        return hdr

    # Convenience ----------------------------------------------------------
    @property
    def shape(self) -> Tuple[int, int]:
        return self.height, self.width

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.time_sec + self.time_nsec / 1e9, tz=timezone.utc)

    def to_json(self, extra: bytes | None = None) -> str:
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
# Main extractor class
# ---------------------------------------------------------------------------
class Movie2Tiff:
    """Extract every frame from a TemI movie to TIFF or PNG and return focus scores."""

    def __init__(self, compression: str = "tiff_lzw", downsample: bool = True, convert_8bit: bool = True, output_format: str = "tiff") -> None:
        compression = compression.lower()
        output_format = output_format.lower()
        
        if output_format not in ["tiff", "png"]:
            raise ValueError(f"Unsupported output format '{output_format}'. Choose from 'tiff', 'png'")
        
        if output_format == "tiff" and compression not in _LOSSLESS_TIFF:
            raise ValueError(
                f"Unsupported compression '{compression}'. Choose from {', '.join(sorted(_LOSSLESS_TIFF))}")
        
        self.compression = compression
        self.downsample = downsample
        self.convert_8bit = convert_8bit
        self.output_format = output_format

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def convert(
        self,
        movie_name: str | Path,
        file_stub: str | Path | None = None,
    ) -> Tuple[List[Path], List[float], List[float]]:
        """Process **all** frames and return filenames + focus scores.

        Parameters
        ----------
        movie_name : path-like
            TemI movie file.
        file_stub : str or path-like or ``None``
            Base name for output files – if ``None`` or empty, the movie’s
            *stem* is used.  For example, movie `clip.temi` → `clip_0001.tif`,
            `clip_0002.tif`, …

        Returns
        -------
        (list[Path], list[float], list[float])
            *Absolute* paths of written TIFFs, their corresponding focus
            scores, and highest pixel values (same order).
        """
        movie_p = Path(movie_name)
        if not movie_p.exists():
            raise FileNotFoundError(movie_p)

        # Determine stub path
        if not file_stub:
            stub_p = movie_p.with_suffix("")  # removes .temi, keeps dir
        else:
            stub_p = Path(file_stub).expanduser().resolve()
        # Directory: use stub's parent (or movie's if stub has no parent)
        out_dir = stub_p.parent if stub_p.parent != Path("") else movie_p.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        data = movie_p.read_bytes()
        frames = list(self._iterate_frames(data))
        n_frames = len(frames)
        if n_frames == 0:
            raise ValueError("No TemI frames found")

        width_pad = len(str(n_frames))
        filenames: List[Path] = []
        scores: List[float] = []

        for idx, (hdr, extra, mv) in enumerate(frames, start=1):
            arr = self._decode_frame(hdr, mv)
            score = self._calculate_focus_score(arr)
            scores.append(score)

            # Determine file extension based on output format
            ext = "png" if self.output_format == "png" else "tiff"
            out_name = f"{stub_p.stem}_{idx:0{width_pad}d}.{ext}"
            out_path = out_dir / out_name
            self._save_image(arr, out_path, hdr, extra, score)
            filenames.append(out_path.resolve())

        return filenames, scores

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _iterate_frames(data: bytes) -> Iterator[Tuple[FrameHeader, bytes, memoryview]]:
        magic = CAMERA_MOVIE_MAGIC.to_bytes(4, "little")
        off = 0
        total = len(data)
        while off < total:
            idx = data.find(magic, off)
            if idx == -1:
                break
            hdr = FrameHeader.from_bytes(data[idx : idx + CAMERA_HEADER_LEN])
            extra_start = idx + CAMERA_HEADER_LEN
            extra_end = idx + hdr.length_header
            extra = data[extra_start:extra_end]
            frame_start = extra_end
            frame_end = frame_start + hdr.length_data
            yield hdr, extra, memoryview(data)[frame_start:frame_end]
            off = frame_end

    # -------------- Focus metric ---------------
    @staticmethod
    def _calculate_focus_score(arr: np.ndarray) -> float:
        """Variance of Laplacian – higher ⇒ sharper."""
        if arr.dtype != np.float64:
            img = arr.astype(np.float64)
        else:
            img = arr  # zero-copy
        # Exclude 1-pixel border to keep indexing simple
        lap = (
            -4 * img[1:-1, 1:-1]
            + img[:-2, 1:-1] + img[2:, 1:-1]
            + img[1:-1, :-2] + img[1:-1, 2:]
        )
        return float(np.var(lap))

    @staticmethod
    def _calculate_highest_pixel_value(arr: np.ndarray) -> float:
        """Highest pixel value – higher ⇒ brighter."""
        if arr.dtype != np.float64:
            img = arr.astype(np.float64)
        else:
            img = arr  # zero-copy
        return float(np.max(img))

    # -------------- Image processing helpers ---------------
    @staticmethod
    def _downsample_array(arr: np.ndarray, method: str = "bilinear") -> np.ndarray:
        """Downsample array to 25% area (50% linear) using various methods."""
        h, w = arr.shape
        new_h, new_w = h // 2, w // 2
        
        if method == "decimation":
            # Simple decimation - fastest but can cause aliasing
            return arr[::2, ::2]
        
        elif method == "averaging":
            # Average 2x2 blocks - good anti-aliasing, preserves intensity
            # Ensure even dimensions
            arr_crop = arr[:new_h*2, :new_w*2]
            return (arr_crop[0::2, 0::2] + arr_crop[1::2, 0::2] + 
                   arr_crop[0::2, 1::2] + arr_crop[1::2, 1::2]) // 4
        
        elif method == "bilinear":
            # Bilinear interpolation - good quality, smooth
            try:
                from scipy import ndimage
                return ndimage.zoom(arr, 0.5, order=1, prefilter=False)
            except ImportError:
                print("Warning: scipy not available, falling back to averaging.")
                # Fallback to averaging if scipy not available
                return Movie2Tiff._downsample_array(arr, method="averaging")
        
        elif method == "lanczos":
            # Lanczos - highest quality but slowest
            from PIL import Image
            pil_img = Image.fromarray(arr)
            resized = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            return np.array(resized)
        
        else:
            raise ValueError(f"Unknown downsampling method: {method}")
    
    @staticmethod
    def _convert_to_8bit(arr: np.ndarray, method: str = "linear") -> np.ndarray:
        """Convert 16-bit array to 8-bit using various normalization methods."""
        if arr.dtype == np.uint8:
            return arr  # Already 8-bit
        
        if method == "linear":
            # Simple linear scaling from full range
            arr_float = arr.astype(np.float64)
            return ((arr_float / arr_float.max()) * 255).astype(np.uint8)
        
        elif method == "percentile":
            # Percentile-based normalization (like your image viewer)
            p2, p98 = np.percentile(arr, (2, 98))
            arr_clipped = np.clip(arr, p2, p98)
            arr_float = arr_clipped.astype(np.float64)
            return ((arr_float - p2) * 255 / (p98 - p2)).astype(np.uint8)
        
        elif method == "histogram_equalization":
            # Histogram equalization for better contrast
            # Simple implementation without OpenCV
            hist, bins = np.histogram(arr.flatten(), 256, [arr.min(), arr.max()])
            cdf = hist.cumsum()
            cdf_normalized = cdf * 255 / cdf[-1]
            return np.interp(arr.flatten(), bins[:-1], cdf_normalized).reshape(arr.shape).astype(np.uint8)
        
        else:
            raise ValueError(f"Unknown 8-bit conversion method: {method}")

    # -------------- Frame decoding -------------
    def _decode_frame(self, hdr: FrameHeader, buf: memoryview) -> np.ndarray:
        h, w = hdr.shape
        stride = hdr.stride

        if hdr.pixelformat == CAMERA_PIXELFORMAT_MONO_8:
            out = np.empty((h, w), dtype=np.uint8)
            for r in range(h):
                off = r * stride
                out[r] = np.frombuffer(buf[off : off + w], dtype=np.uint8, count=w)
            
            # Apply downsampling if requested
            if self.downsample:
                out = self._downsample_array(out, method="averaging")
            
            return out

        if hdr.pixelformat == CAMERA_PIXELFORMAT_MONO_16:
            out = np.empty((h, w), dtype=np.uint16)
            for r in range(h):
                off = r * stride
                row = np.frombuffer(buf[off : off + w * 2], dtype="<u2", count=w)
                if hdr.endianness == G_BIG_ENDIAN:
                    row = row.byteswap()
                out[r] = row
            
            # Apply downsampling if requested
            if self.downsample:
                out = self._downsample_array(out, method="averaging")
            
            return out

        if hdr.pixelformat == CAMERA_PIXELFORMAT_MONO_12_PACKED:
            out = np.empty((h, w), dtype=np.uint16)
            for r in range(h):
                off = r * stride
                packed = buf[off : off + ((w + 1) // 2) * 3]
                j = 0
                for c in range(0, w, 2):
                    b0, b1, b2 = packed[j : j + 3]
                    out[r, c] = b0 | ((b1 & 0x0F) << 8)
                    if c + 1 < w:
                        out[r, c + 1] = (b1 >> 4) | (b2 << 4)
                    j += 3
            
            # Apply downsampling if requested
            if self.downsample:
                out = self._downsample_array(out, method="averaging")
            
            return out

        if hdr.pixelformat == CAMERA_PIXELFORMAT_MONO_32:
            out = np.empty((h, w), dtype=np.uint32)
            for r in range(h):
                off = r * stride
                row = np.frombuffer(buf[off : off + w * 4], dtype="<u4", count=w)
                if hdr.endianness == G_BIG_ENDIAN:
                    row = row.byteswap()
                out[r] = row
            
            # Apply downsampling if requested
            if self.downsample:
                out = self._downsample_array(out, method="averaging")
            
            return out

        raise NotImplementedError(f"Unsupported pixel format 0x{hdr.pixelformat:08X}")

    # -------------- Image writing ---------------
    def _save_image(
        self,
        arr: np.ndarray,
        path: Path,
        hdr: FrameHeader,
        extra: bytes,
        focus_score: float,
    ) -> None:
        """Save image as TIFF or PNG based on output_format setting."""
        if self.output_format == "png":
            self._save_png(arr, path, hdr, extra, focus_score)
        else:
            self._save_tiff(arr, path, hdr, extra, focus_score)

    def _save_tiff(
        self,
        arr: np.ndarray,
        path: Path,
        hdr: FrameHeader,
        extra: bytes,
        focus_score: float,
    ) -> None:
        # Apply 8-bit conversion if requested
        if self.convert_8bit and arr.dtype != np.uint8:
            arr = self._convert_to_8bit(arr, method="percentile")
        
        img = Image.fromarray(arr)
        try:
            ifd = TiffImagePlugin.ImageFileDirectory_v2()
        except AttributeError:
            ifd = TiffImagePlugin.ImageFileDirectory()

        meta_json = json.loads(hdr.to_json(extra))
        meta_json["focus_var_lap"] = focus_score
        
        # Add processing metadata
        if self.downsample:
            meta_json["processed_downsampled"] = True
            meta_json["downsampling_factor"] = 0.5
        if self.convert_8bit:
            meta_json["processed_8bit_conversion"] = True
            
        ifd[TAG_IMAGE_DESCRIPTION] = json.dumps(meta_json, indent=2)
        ifd[TAG_DATETIME] = hdr.timestamp.strftime("%Y:%m:%d %H:%M:%S")

        img.save(
            str(path),
            format="TIFF",
            compression=None if self.compression == "raw" else self.compression,
            tiffinfo=ifd,
        )

    def _save_png(
        self,
        arr: np.ndarray,
        path: Path,
        hdr: FrameHeader,
        extra: bytes,
        focus_score: float,
    ) -> None:
        # PNG only supports 8-bit, so always convert if needed
        if arr.dtype != np.uint8:
            arr = self._convert_to_8bit(arr, method="percentile")
        
        # Explicitly create grayscale image from 8-bit array
        img = Image.fromarray(arr, mode='L')  # 'L' mode ensures grayscale
        
        # Create metadata for PNG (stored as text chunks)
        meta_json = json.loads(hdr.to_json(extra))
        meta_json["focus_var_lap"] = focus_score
        
        # Add processing metadata
        if self.downsample:
            meta_json["processed_downsampled"] = True
            meta_json["downsampling_factor"] = 0.5
        if self.convert_8bit:
            meta_json["processed_8bit_conversion"] = True
        
        # PNG metadata - handle different Pillow versions
        try:
            pnginfo = PngInfo()
            pnginfo.add_text("Description", json.dumps(meta_json, indent=2))
            pnginfo.add_text("DateTime", hdr.timestamp.strftime("%Y:%m:%d %H:%M:%S"))
            pnginfo.add_text("FocusScore", str(focus_score))
            
            img.save(
                str(path),
                format="PNG",
                pnginfo=pnginfo,
                optimize=True  # Optimize PNG file size
            )
        except (AttributeError, NameError):
            # Fallback for older Pillow versions without proper PNG metadata support
            print("Warning: PNG metadata not supported in this Pillow version, saving without metadata")
            img.save(
                str(path),
                format="PNG",
                optimize=True
            )


# ---------------------------------------------------------------------------
# CLI entry (optional)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import glob

    p = argparse.ArgumentParser(description="Extract every frame of TemI movies to TIFFs or PNGs with focus scores")
    
    # Movie input - can be single file or pattern for batch processing
    p.add_argument("movie", help="TemI movie file or glob pattern (e.g., '*.temi', 'movies/*.temi')")
    p.add_argument("stub", nargs="?", default="", help="Filename stub for single file (ignored in batch mode)")
    
    # Processing options
    p.add_argument("-c", "--compression", default="tiff_lzw", help="TIFF compression (ignored for PNG)")
    p.add_argument("-f", "--format", default="tiff", choices=["tiff", "png"], help="Output format")
    p.add_argument("--no-downsample", action="store_true", help="Disable downsampling to 25% area")
    p.add_argument("--no-8bit", action="store_true", help="Disable 8-bit conversion")
    
    # Batch processing options
    p.add_argument("-b", "--batch", action="store_true", 
                   help="Enable batch mode - treat 'movie' argument as glob pattern")
    p.add_argument("--output-dir", help="Output directory for batch processing (default: same as input)")
    p.add_argument("--dry-run", action="store_true", help="Show what files would be processed without actually processing")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output during batch processing")
    
    args = p.parse_args()

    # Determine if we're in batch mode
    batch_mode = args.batch or ('*' in args.movie or '?' in args.movie)
    
    if batch_mode:
        # Batch processing
        movie_files = glob.glob(args.movie)
        if not movie_files:
            print(f"No files found matching pattern: {args.movie}")
            exit(1)
        
        movie_files.sort()  # Process in alphabetical order
        
        if args.dry_run:
            print(f"Would process {len(movie_files)} files:")
            for movie_file in movie_files:
                print(f"  {movie_file}")
            exit(0)
        
        print(f"Processing {len(movie_files)} movie files...")
        
        conv = Movie2Tiff(
            compression=args.compression,
            output_format=args.format,
            downsample=not args.no_downsample,
            convert_8bit=not args.no_8bit
        )
        
        total_files = 0
        total_scores = []
        
        for i, movie_file in enumerate(movie_files, 1):
            if args.verbose:
                print(f"\n[{i}/{len(movie_files)}] Processing: {Path(movie_file).name}")
            
            try:
                # For batch mode, use output directory if specified
                if args.output_dir:
                    output_dir = Path(args.output_dir)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    # Use movie filename as stub in the output directory
                    stub = output_dir / Path(movie_file).stem
                else:
                    # Use default behavior (same directory as movie, movie stem as stub)
                    stub = ""
                
                files, scores = conv.convert(movie_file, stub)
                total_files += len(files)
                total_scores.extend(scores)
                
                if args.verbose:
                    print(f"  Generated {len(files)} frames, avg focus: {np.mean(scores):.1f}")
                else:
                    print(f"{Path(movie_file).name}: {len(files)} frames")
                    
            except Exception as e:
                print(f"Error processing {movie_file}: {e}")
                continue
        
        print(f"\nBatch complete: {total_files} total frames from {len(movie_files)} movies")
        if total_scores:
            print(f"Overall focus stats - Mean: {np.mean(total_scores):.1f}, "
                  f"Min: {min(total_scores):.1f}, Max: {max(total_scores):.1f}")
    
    else:
        # Single file processing (original behavior)
        conv = Movie2Tiff(
            compression=args.compression,
            output_format=args.format,
            downsample=not args.no_downsample,
            convert_8bit=not args.no_8bit
        )
        files, scores, _ = conv.convert(args.movie, args.stub)
        for fp, sc in zip(files, scores):
            print(f"{fp.name}\tfocus={sc:.1f}")
