"""Command line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from .dsdl import load_dsdl
from .generator import GenerationConfig, generate_module
from .naming import to_pascal


def default_class_name(module_name: str) -> str:
    if module_name == "dronecan":
        return "DroneCAN"
    if module_name.startswith("dronecan_"):
        return "DroneCAN" + to_pascal(module_name[len("dronecan_") :])
    return to_pascal(module_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xr_dronecan_dsdlc")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate an XRobot/LibXR module from DroneCAN DSDL")
    gen.add_argument("dsdl_dir", nargs="*", type=Path, help="DSDL root namespace directories")
    gen.add_argument("-I", "--lookup-dir", action="append", type=Path, default=[], help="Additional DSDL lookup root")
    gen.add_argument("--builtin-dsdl", action="store_true", help="Use the DroneCAN DSDL roots bundled with the dronecan Python package")
    gen.add_argument("--type", action="append", default=[], help="Full DSDL type name to emit; repeatable. Defaults to all parsed source types")
    gen.add_argument("-o", "--output", required=True, type=Path, help="Generated module output directory")
    gen.add_argument("--module-name", default="dronecan_generated", help="XRobot module name")
    gen.add_argument("--class-name", help="Generated XRobot Application class name")
    gen.add_argument("--root-namespace", default="DroneCANGenerated", help="C++ namespace for generated DSDL types")
    gen.add_argument("--node-name", default="org.libxr.dronecan.generated", help="Default DroneCAN node name")
    gen.add_argument("--node-id", default=10, type=int, help="Default node ID in generated module.yaml")
    gen.add_argument("--node-status-period-ms", default=1000, type=int, help="Default NodeStatus period")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        dsdl_set = load_dsdl(args.dsdl_dir, args.lookup_dir, include_builtin=args.builtin_dsdl)
        selected = dsdl_set.select_with_dependencies(args.type)
        class_name = args.class_name or default_class_name(args.module_name)
        cfg = GenerationConfig(
            output=args.output,
            module_name=args.module_name,
            class_name=class_name,
            root_namespace=args.root_namespace,
            node_name=args.node_name,
            default_node_id=args.node_id,
            default_node_status_period_ms=args.node_status_period_ms,
        )
        generate_module(cfg, selected)
        print(f"[OK] Generated {cfg.module_name} at {cfg.output}")
        print(f"[OK] Emitted {len(selected)} DSDL type(s)")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
