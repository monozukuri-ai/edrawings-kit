from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import build_info, inspect_file, probe_file, read_file
from .errors import EdrawingsError
from .limits import Limits


def main(argv: list[str] | None = None) -> int:
    # JSON and help are UTF-8 even when redirected on Windows or in an ASCII locale.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="edrawings-kit")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("info", help="Show parser version and capabilities")
    for command in (
        "probe",
        "inspect",
        "extract",
        "hsf-header",
        "hsf",
        "scene",
        "drawing",
        "display",
        "verify",
    ):
        sub = subs.add_parser(command)
        sub.add_argument("path", type=Path)
        sub.add_argument("--limits", choices=("desktop", "service"), default="desktop")
        if command in ("extract", "hsf-header", "hsf", "scene", "drawing", "display"):
            sub.add_argument(
                "--entry",
                required=command == "extract",
                help="Stable entry ID from inspect",
            )
        if command == "extract":
            sub.add_argument("--output", type=Path, required=True)
        if command in ("hsf", "scene", "drawing"):
            sub.add_argument("--mode", choices=("partial", "strict"), default="partial")
        if command in ("hsf", "scene", "drawing", "display"):
            display = command == "display"
            sub.add_argument(
                "--user-data-profile",
                choices=(
                    "disabled",
                    "edrawings_first_be_v2",
                    "edrawings_be_envelope_v1",
                ),
                default="edrawings_be_envelope_v1" if display else "disabled",
            )
            sub.add_argument(
                "--image-profile",
                choices=("disabled", "edrawings_1910_u32_v1"),
                default="edrawings_1910_u32_v1" if display else "disabled",
            )
        if command in ("scene", "drawing", "display"):
            sub.add_argument(
                "--import-root",
                help=(
                    "Explicit absolute import segment for inventory; "
                    "external state remains unknown"
                ),
            )
            sub.add_argument(
                "--placement",
                choices=("verified", "scene_graph_v1"),
                default="scene_graph_v1" if command == "display" else "verified",
                help=(
                    "scene_graph_v1 estimates instances when verified placement "
                    "is withheld"
                ),
            )
        if command == "display":
            sub.add_argument(
                "--colors",
                choices=("materials_xml", "hsf_only"),
                default="materials_xml",
            )
            sub.add_argument(
                "--configuration",
                help="Saved configuration to show (config name or configN segment)",
            )
            sub.add_argument(
                "--display-state",
                help="Display state to apply (dispN segment or its name)",
            )
            sub.add_argument(
                "--include-hidden",
                action="store_true",
                help="Keep components eDrawings hides (visibility buffer 0)",
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "info":
            result = build_info().to_dict()
        else:
            limits = Limits.service() if args.limits == "service" else Limits.desktop()
            if args.command == "probe":
                result = probe_file(args.path, limits=limits).to_dict()
            elif args.command == "inspect":
                result = inspect_file(args.path, limits=limits).to_dict()
            else:
                doc = read_file(args.path, limits=limits, read_metadata=False)
                if args.command == "extract":
                    extraction = doc.extract(args.entry)
                    # Explicit destination only; never use an entry name or overwrite.
                    with args.output.open("xb") as target:
                        target.write(extraction.data)
                    result = extraction.info.to_dict()
                elif args.command == "hsf-header":
                    result = doc.inspect_hsf(args.entry).to_dict()
                elif args.command == "drawing":
                    result = doc.read_drawing(
                        args.entry,
                        mode=args.mode,
                        user_data_profile=args.user_data_profile,
                        image_profile=args.image_profile,
                        import_root=args.import_root,
                        placement=args.placement,
                    ).summary.to_dict()
                elif args.command == "scene":
                    result = doc.read_scene(
                        args.entry,
                        mode=args.mode,
                        user_data_profile=args.user_data_profile,
                        image_profile=args.image_profile,
                        import_root=args.import_root,
                        placement=args.placement,
                    ).summary.to_dict()
                elif args.command == "display":
                    result = doc.read_display(
                        args.entry,
                        placement=args.placement,
                        colors=args.colors,
                        configuration=args.configuration,
                        display_state=args.display_state,
                        include_hidden=args.include_hidden,
                        user_data_profile=args.user_data_profile,
                        image_profile=args.image_profile,
                        import_root=args.import_root,
                    ).summary.to_dict()
                elif args.command == "hsf":
                    result = doc.parse_hsf(
                        args.entry,
                        mode=args.mode,
                        user_data_profile=args.user_data_profile,
                        image_profile=args.image_profile,
                    ).summary.to_dict()
                else:
                    result = {"entries": [item.to_dict() for item in doc.verify_all()]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except EdrawingsError as error:
        print(
            json.dumps({"error": error.diagnostic.to_dict()}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    except OSError as error:
        print(
            json.dumps({"error": {"code": "io.error", "message": str(error)}}),
            file=sys.stderr,
        )
        return 2
