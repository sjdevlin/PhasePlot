"""Read-only connectivity test for an Olympus IX81 through Micro-Manager.

This utility initializes the Olympus hub and selected frame peripherals, then
prints their current state.  It never writes a focus or turret position.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pymmcore


DEFAULT_MM_PATH = Path(r"C:\Program Files\Micro-Manager-2.0")
READ_ONLY_DEVICES = ("ManualFocus", "Objective", "FilterCube", "FilterWheel")


def configure_serial_port(core: pymmcore.CMMCore, port: str) -> None:
    core.loadDevice(port, "SerialManager", port)
    settings = {
        "AnswerTimeout": "500",
        "BaudRate": "19200",
        "DelayBetweenCharsMs": "0",
        "Handshaking": "Off",
        "Parity": "Even",
        "StopBits": "2",
    }
    for name, value in settings.items():
        core.setProperty(port, name, value)
    core.initializeDevice(port)


def print_device_state(core: pymmcore.CMMCore, label: str, device_name: str) -> None:
    description = core.getDeviceDescription(label)
    print(f"{device_name}: {description}")
    if device_name == "ManualFocus":
        print(f"  position: {core.getPosition(label):g} um")
        return

    print(f"  position: {core.getState(label)}")
    labels = list(core.getStateLabels(label))
    if labels:
        current = core.getState(label)
        current_label = labels[current] if current < len(labels) else "unlabelled"
        print(f"  label: {current_label}")
        print(f"  available positions: {len(labels)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9", help="IX81 frame serial port")
    parser.add_argument(
        "--micromanager-path",
        type=Path,
        default=DEFAULT_MM_PATH,
        help="folder containing mmgr_dal_Olympus.dll",
    )
    parser.add_argument(
        "--focus-delta",
        type=float,
        help="move focus by this many um, hold briefly, then return",
    )
    parser.add_argument(
        "--objective-position",
        type=int,
        choices=range(1, 7),
        help="switch to this objective position (1-6), hold, then return",
    )
    parser.add_argument(
        "--filter-cube-position",
        type=int,
        choices=range(1, 7),
        help="switch to this filter-cube position (1-6), hold, then return",
    )
    args = parser.parse_args()

    if args.focus_delta is not None and not 0 < abs(args.focus_delta) <= 100:
        parser.error("--focus-delta must be non-zero and no greater than 100 um")

    adapter = args.micromanager_path / "mmgr_dal_Olympus.dll"
    if not adapter.exists():
        raise SystemExit(f"Olympus Micro-Manager adapter not found: {adapter}")

    # Windows does not automatically search the Micro-Manager directory for
    # dependencies such as libserialport.dll when Python loads an adapter.
    dll_directory = os.add_dll_directory(str(args.micromanager_path))
    core = pymmcore.CMMCore()
    core.enableStderrLog(False)
    core.setDeviceAdapterSearchPaths([str(args.micromanager_path)])

    try:
        print(f"Opening {args.port} at 19200 baud, even parity, 2 stop bits...")
        configure_serial_port(core, args.port)

        core.loadDevice("IX81", "Olympus", "OlympusHub")
        core.setProperty("IX81", "Port", args.port)
        core.initializeDevice("IX81")
        print("OlympusHub initialized successfully.")

        try:
            installed = list(core.getInstalledDevices("IX81"))
        except Exception:
            # This legacy adapter exposes a hub but does not implement the
            # optional MMCore installed-device discovery operation.
            installed = []
        if installed:
            print("Hub-reported peripherals:", ", ".join(installed))

        initialized: dict[str, str] = {}
        for device_name in READ_ONLY_DEVICES:
            label = f"IX81-{device_name}"
            try:
                core.loadDevice(label, "Olympus", device_name)
                core.setParentLabel(label, "IX81")
                core.initializeDevice(label)
                initialized[device_name] = label
                print_device_state(core, label, device_name)
            except Exception as error:
                print(f"{device_name}: unavailable ({error})")

        if args.focus_delta is not None:
            label = initialized.get("ManualFocus")
            if label is None:
                raise RuntimeError("ManualFocus is unavailable; focus test cannot run")
            start = core.getPosition(label)
            target = start + args.focus_delta
            moved = False
            try:
                print(f"Moving focus from {start:g} um to {target:g} um...")
                core.setPosition(label, target)
                moved = True
                core.waitForDevice(label)
                print(f"Focus after move: {core.getPosition(label):g} um")
                time.sleep(2)
            finally:
                if moved:
                    core.setPosition(label, start)
                    core.waitForDevice(label)
                    print(f"Focus after return: {core.getPosition(label):g} um")
        if args.objective_position is not None:
            label = initialized.get("Objective")
            if label is None:
                raise RuntimeError("Objective is unavailable; turret test cannot run")
            start = core.getState(label)
            target = args.objective_position - 1
            if target == start:
                raise RuntimeError(
                    f"Objective is already at position {args.objective_position}"
                )
            moved = False
            try:
                print(f"Switching objective from position {start + 1} to {target + 1}...")
                core.setState(label, target)
                moved = True
                core.waitForDevice(label)
                print(f"Objective after switch: position {core.getState(label) + 1}")
                time.sleep(2)
            finally:
                if moved:
                    core.setState(label, start)
                    core.waitForDevice(label)
                    print(f"Objective after return: position {core.getState(label) + 1}")
        if args.filter_cube_position is not None:
            label = initialized.get("FilterCube")
            if label is None:
                raise RuntimeError("FilterCube is unavailable; turret test cannot run")
            start = core.getState(label)
            target = args.filter_cube_position - 1
            if target == start:
                raise RuntimeError(
                    f"Filter cube is already at position {args.filter_cube_position}"
                )
            moved = False
            try:
                print(f"Switching filter cube from position {start + 1} to {target + 1}...")
                core.setState(label, target)
                moved = True
                core.waitForDevice(label)
                print(f"Filter cube after switch: position {core.getState(label) + 1}")
                time.sleep(2)
            finally:
                if moved:
                    core.setState(label, start)
                    core.waitForDevice(label)
                    print(f"Filter cube after return: position {core.getState(label) + 1}")
        if (
            args.focus_delta is None
            and args.objective_position is None
            and args.filter_cube_position is None
        ):
            print("Read-only IX81 test complete; no positions were changed.")
    finally:
        core.reset()
        dll_directory.close()


if __name__ == "__main__":
    main()
