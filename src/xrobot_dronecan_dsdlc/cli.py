"""命令行入口。

Command line entrypoint.
"""

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

    gen = sub.add_parser("generate", help="从 DroneCAN DSDL 生成 XRobot/LibXR 模块 / Generate an XRobot/LibXR module from DroneCAN DSDL")
    gen.add_argument("dsdl_dir", nargs="*", type=Path, help="DSDL 根命名空间目录 / DSDL root namespace directories")
    gen.add_argument("-I", "--lookup-dir", action="append", type=Path, default=[], help="额外 DSDL 查找根目录 / Additional DSDL lookup root")
    gen.add_argument("--builtin-dsdl", action="store_true", help="使用内置 DroneCAN DSDL 根目录 / Use bundled DroneCAN DSDL roots")
    gen.add_argument("--type", action="append", default=None, help="要输出的完整 DSDL 类型名，可重复；默认 uavcan.protocol.NodeStatus / Full DSDL type name to emit; repeatable; defaults to uavcan.protocol.NodeStatus")
    gen.add_argument("-o", "--output", required=True, type=Path, help="生成模块输出目录 / Generated module output directory")
    gen.add_argument("--module-name", default="dronecan_generated", help="XRobot 模块名 / XRobot module name")
    gen.add_argument("--class-name", help="生成的 XRobot Application 类名 / Generated XRobot Application class name")
    gen.add_argument("--root-namespace", default="DroneCANGenerated", help="生成 DSDL 类型使用的 C++ 命名空间 / C++ namespace for generated DSDL types")
    gen.add_argument("--node-name", default="org.libxr.dronecan.generated", help="默认 DroneCAN 节点名 / Default DroneCAN node name")
    gen.add_argument("--node-id", default=10, type=int, help="manifest 中的默认节点 ID / Default node ID in the manifest")
    gen.add_argument("--node-status-period-ms", default=1000, type=int, help="默认 NodeStatus 周期 / Default NodeStatus period")
    gen.add_argument("--core-module-id", default="CaFeZn/dronecan_core", help="dronecan_core 的完整 XRobot 模块 ID / Full XRobot module ID for dronecan_core")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        dsdl_set = load_dsdl(args.dsdl_dir, args.lookup_dir, include_builtin=args.builtin_dsdl)
        requested_types = args.type if args.type is not None else ["uavcan.protocol.NodeStatus"]
        selected = dsdl_set.select_with_dependencies(requested_types)
        class_name = args.class_name or default_class_name(args.module_name)
        cfg = GenerationConfig(
            output=args.output,
            module_name=args.module_name,
            class_name=class_name,
            root_namespace=args.root_namespace,
            node_name=args.node_name,
            default_node_id=args.node_id,
            default_node_status_period_ms=args.node_status_period_ms,
            core_module_id=args.core_module_id,
        )
        generate_module(cfg, selected)
        print(f"[OK] 已生成 {cfg.module_name}: {cfg.output} / Generated {cfg.module_name} at {cfg.output}")
        print(f"[OK] 已输出 {len(selected)} 个 DSDL 类型 / Emitted {len(selected)} DSDL type(s)")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
