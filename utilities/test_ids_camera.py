"""Test connectivity and one-frame acquisition from an IDS uEye+ camera."""

from __future__ import annotations

import argparse
from pathlib import Path

from hardware.ids_camera import IDSCamera


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="U3-3990SE-M-GL")
    parser.add_argument("--serial", help="optional camera serial number")
    parser.add_argument("--exposure", type=float, help="optional exposure time in microseconds")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/ids_camera_test.tiff"),
        help="output image path (default: outputs/ids_camera_test.tiff)",
    )
    args = parser.parse_args()

    print("Initialising IDS peak and searching for cameras...")
    with IDSCamera(model=args.model, serial_number=args.serial) as camera:
        info = camera.device_info()
        print(
            f"Connected: {info['vendor']} {info['model']} "
            f"(serial {info['serial']})"
        )
        if args.exposure is not None:
            camera.set_exposure_time(args.exposure)
            print(f"Exposure set to {args.exposure:g} us")

        frame = camera.capture_image(output_path=args.output)
        print(
            "Frame acquired: "
            f"{frame['width']} x {frame['height']}, "
            f"{frame['pixel_format']}, timestamp {frame['timestamp_ns']} ns"
        )
        print(f"Saved image: {frame['output_path']}")


if __name__ == "__main__":
    main()
