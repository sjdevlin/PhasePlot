#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import AppConfig, DatabaseService, PhaseDiagramAnalyzer


def _discover_default_config() -> str:
    candidates = [
        Path("config.yaml"),
        Path("config_mac.yaml"),
        Path("config_20X.yaml"),
        Path("config_40X.yaml"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "No config file found. Expected one of: config.yaml, config_mac.yaml, config_20X.yaml, config_40X.yaml."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate dense/dilute concentration estimates and a ratio-fit plot for a target "
            "result run temperature and LED channel."
        )
    )
    parser.add_argument("result_run_id", type=int, help="Result run id")
    parser.add_argument("target_temperature", type=float, help="Target temperature in Celsius")
    parser.add_argument("led_channel", type=int, help="LED channel number (for example 5 or 6)")

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file (defaults to config.yaml/config_mac.yaml/config_20X.yaml/config_40X.yaml).",
    )
    parser.add_argument(
        "--temperature-tolerance",
        type=float,
        default=0.15,
        help="Allowed absolute temperature delta from target in Celsius (default: 0.15).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs/phase_diagrams",
        help="Directory root for plots/crops/summary output.",
    )
    parser.add_argument(
        "--max-droplets",
        type=int,
        default=5,
        help="Maximum number of droplet crops per site (default: 5).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config_path = args.config or _discover_default_config()
    config = AppConfig(config_path)
    db = DatabaseService(config.get("sqlite_db"))

    analyzer = PhaseDiagramAnalyzer(
        db_service=db,
        image_directory=config.get("image_file_directory"),
        output_directory=args.output_dir,
        temperature_tolerance=args.temperature_tolerance,
        max_droplets_per_site=args.max_droplets,
    )

    try:
        summary = analyzer.analyze(
            result_run_id=args.result_run_id,
            target_temperature=args.target_temperature,
            led_channel=args.led_channel,
        )
    except Exception as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1

    fit = summary.get("fit", {})
    print("Analysis complete")
    print(f"  Experiment: {summary['experiment_id']}")
    print(f"  Result run: {summary['result_run_id']}")
    print(f"  Temperature: {summary['target_temperature_c']:.2f} C")
    print(f"  LED channel: {summary['led_channel']}")
    print(f"  Valid sites: {summary['valid_site_count']}")
    print(f"  Dropped sites: {summary['dropped_site_count']}")
    if fit.get("success"):
        print(f"  Dilute concentration (uM): {fit['dilute_concentration_uM']:.6f}")
        print(f"  Dense concentration (uM): {fit['dense_concentration_uM']:.6f}")
        print(f"  Linear fit R^2: {fit['r_squared']:.6f}")
    else:
        print(f"  Fit status: failed ({fit.get('reason', 'unknown')})")

    print(f"  Ratio plot: {summary['plot_path']}")
    print(f"  Summary JSON: {summary['summary_json_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
