"""Connect to a Thorlabs DC4100 and optionally pulse one LED channel."""

from __future__ import annotations

import argparse

from hardware.thorlabs_dc4100 import DC4100Error, ThorlabsDC4100


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM8", help="Windows COM port (default: COM8)")
    parser.add_argument("--channel", type=int, choices=range(1, 5), help="LED channel to pulse (1-4)")
    parser.add_argument("--brightness", type=float, help="pulse brightness in percent (0-100)")
    parser.add_argument("--pulse-seconds", type=float, help="pulse duration, maximum 60 seconds")
    args = parser.parse_args()

    control_values = (args.channel, args.brightness, args.pulse_seconds)
    if any(value is not None for value in control_values) and not all(
        value is not None for value in control_values
    ):
        parser.error("--channel, --brightness, and --pulse-seconds must be supplied together")

    resource = f"ASRL{args.port.removeprefix('COM')}::INSTR"
    print(f"Connecting to {resource} without resetting the controller...")
    try:
        with ThorlabsDC4100(resource) as controller:
            identity = controller.identity()
            print(
                f"Connected: {identity['manufacturer']} {identity['model']} "
                f"(serial {identity['serial']}, firmware {identity['firmware']})"
            )
            mode_names = {0: "constant current", 1: "brightness", 2: "external control"}
            mode = controller.operation_mode()
            print(f"Operation mode: {mode_names.get(mode, f'unknown ({mode})')}")
            for channel in range(1, 5):
                print(
                    f"Channel {channel}: {'ON' if controller.is_on(channel) else 'off'}, "
                    f"brightness {controller.brightness(channel):g}%, "
                    f"current {controller.constant_current(channel) * 1000:g} mA, "
                    f"limit {controller.current_limit(channel) * 1000:g} mA, "
                    f"wavelength {controller.wavelength(channel):g} nm"
                )

            if args.channel is not None:
                print(
                    f"Pulsing channel {args.channel} at {args.brightness:g}% for "
                    f"{args.pulse_seconds:g} s..."
                )
                controller.pulse(args.channel, args.brightness, args.pulse_seconds)
                print("Pulse complete; previous controller settings restored.")
            else:
                print("Read-only test complete; no LED settings were changed.")
    except DC4100Error as error:
        raise SystemExit(f"DC4100 test failed: {error}") from error


if __name__ == "__main__":
    main()
