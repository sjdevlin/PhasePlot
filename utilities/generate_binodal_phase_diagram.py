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
            "result run temperature using LED5 for droplets and LED6 for condensates."
        )
    )
    parser.add_argument("result_run_id", type=int, help="Result run id")
    parser.add_argument("target_temperature", type=float, help="Target temperature in Celsius")
    parser.add_argument(
        "sample_number",
        nargs="?",
        type=int,
        default=None,
        help="Optional sample id filter. If provided, only this sample is analysed.",
    )

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
        help="Number of droplet crops per site from the seed image (default: 5).",
    )
    parser.add_argument(
        "--axis-consistency-tolerance",
        type=float,
        default=0.05,
        help=(
            "Relative tolerance used by circle-fit inlier checks "
            "(default: 0.05, i.e. 5%% of fitted radius)."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="If set, save only the two selected measurement crops per site (LED5 + LED6) with overlays.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config_path = args.config or _discover_default_config()
    config = AppConfig(config_path)
    db = DatabaseService(config.get("sqlite_db"))
    print(f"Using config: {config_path}", flush=True)
    print(f"Opening database: {config.get('sqlite_db')}", flush=True)
    if args.sample_number is not None:
        print(f"Sample filter: {args.sample_number}", flush=True)
    print(f"Debug crop save: {args.debug}", flush=True)

    analyzer = PhaseDiagramAnalyzer(
        db_service=db,
        image_directory=config.get("image_file_directory"),
        output_directory=args.output_dir,
        temperature_tolerance=args.temperature_tolerance,
        max_droplets_per_site=args.max_droplets,
        axis_consistency_tolerance=args.axis_consistency_tolerance,
        debug_save_crops=args.debug,
        progress_callback=lambda msg: print(msg, flush=True),
    )

    try:
        summary = analyzer.analyze(
            result_run_id=args.result_run_id,
            target_temperature=args.target_temperature,
            sample_id=args.sample_number,
        )
    except Exception as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1

    fit = summary.get("fit", {})
    print("Analysis complete")
    print(f"  Experiment: {summary['experiment_id']}")
    print(f"  Result run: {summary['result_run_id']}")
    print(f"  Temperature: {summary['target_temperature_c']:.2f} C")
    if summary.get("sample_filter_id") is not None:
        print(f"  Sample filter: {summary['sample_filter_id']}")
    print(
        "  Channels: "
        f"LED{summary['droplet_led_channel']} (droplet), "
        f"LED{summary['condensate_led_channel']} (condensate)"
    )
    print(f"  Valid sites: {summary['valid_site_count']}")
    print(f"  Dropped sites: {summary['dropped_site_count']}")
    print(
        "  Circle-fit inlier tolerance: "
        f"{summary.get('axis_consistency_tolerance', args.axis_consistency_tolerance):.3f}"
    )
    def _fmt(v):
        return "NA" if v is None else f"{float(v):.2f}"
    print("  Droplet counts by valid site:")
    for row in sorted(
        summary.get("site_measurements", []),
        key=lambda r: (int(r.get("sample_id", -1)), int(r.get("site_number", -1))),
    ):
        print(
            "    "
            f"sample={row.get('sample_id')} "
            f"site={row.get('site_number')} "
            f"candidates_in_range={row.get('droplet_candidate_count_in_range', 0)} "
            f"selected={row.get('selected_droplet_count', row.get('crop_count', 0))} "
            f"valid={row.get('valid_crop_count', 0)} "
            f"debug_csv={row.get('debug_csv_path', '')} "
            f"debug_crops={row.get('debug_crop_directory', '')}"
        )
        for crop in row.get("per_crop_measurements", []):
            print(
                "      PASS "
                f"sample={row.get('sample_id')} "
                f"site={row.get('site_number')} "
                f"crop={int(crop.get('crop_index', -1)) + 1} "
                f"led{summary.get('droplet_led_channel')}stack={crop.get('droplet_stack_number')} "
                f"led{summary.get('condensate_led_channel')}stack={crop.get('condensate_stack_number')}"
            )
        for crop in row.get("dropped_crop_measurements", []):
            print(
                "      DROP "
                f"sample={row.get('sample_id')} "
                f"site={row.get('site_number')} "
                f"crop={int(crop.get('crop_index', -1)) + 1} "
                f"dx_droplet={_fmt(crop.get('droplet_diameter_x_px'))} "
                f"dy_droplet={_fmt(crop.get('droplet_diameter_y_px'))} "
                f"dx_cond={_fmt(crop.get('condensate_diameter_x_px'))} "
                f"dy_cond={_fmt(crop.get('condensate_diameter_y_px'))} "
                f"reason={crop.get('reason', 'unknown')}"
            )

    dropped_sites = summary.get("dropped_sites", [])
    if dropped_sites:
        print("  Dropped site reasons:")
        for row in sorted(
            dropped_sites,
            key=lambda r: (int(r.get("sample_id", -1)), int(r.get("site_number", -1))),
        ):
            print(
                "    "
                f"sample={row.get('sample_id')} "
                f"site={row.get('site_number')} "
                f"reason={row.get('reason', 'unknown')}"
            )
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
