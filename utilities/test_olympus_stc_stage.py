"""Perform a small, reversible movement test with an Olympus STC stage.

Example config.yaml section::

    stage_type: Olympus_STC
    stage_port: COM3
    stage_timeout: 1.0
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from hardware.olympus_stc import OlympusSTC


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--x", type=float, default=0.1, help="relative X movement in mm")
    parser.add_argument("--y", type=float, default=0.0, help="relative Y movement in mm")
    parser.add_argument(
        "--return-to-start",
        action="store_true",
        help="move back by the inverse displacement after the test",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.config.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    port = config.get("stage_port")
    if not port:
        raise SystemExit(f"No 'stage_port' is set in {args.config}")

    timeout = float(config.get("stage_timeout", 1.0))
    print(f"Connecting to Olympus STC on {port} at 19200 8-N-1...")

    with OlympusSTC(port=port, timeout=timeout) as stage:
        identity = stage.identify()
        if not identity:
            raise RuntimeError("The stage did not answer the 'identify' command")
        print(f"Controller: {identity}")

        before = stage.get_position()
        print(f"Position before: x={before[0]:g} mm, y={before[1]:g} mm")
        print(f"Moving relatively by x={args.x:g} mm, y={args.y:g} mm")
        stage.move_relative(args.x, args.y)
        stage.wait_until_ready()

        after = stage.get_position()
        print(f"Position after:  x={after[0]:g} mm, y={after[1]:g} mm")

        if args.return_to_start:
            print("Returning by the inverse displacement...")
            stage.move_relative(-args.x, -args.y)
            stage.wait_until_ready()
            returned = stage.get_position()
            print(f"Final position:  x={returned[0]:g} mm, y={returned[1]:g} mm")


if __name__ == "__main__":
    main()
