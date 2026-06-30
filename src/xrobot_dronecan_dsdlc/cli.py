"""命令行入口。

Command line entrypoint.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

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
    gen.add_argument("--config", type=Path, help="从独立 YAML 文件读取 DSDL 生成配置 / Read generation config from a standalone YAML file")
    gen.add_argument("--xrobot-yaml", type=Path, help="从用户工程 XRobot YAML 读取 DSDL 生成配置 / Read generation config from project XRobot YAML")
    gen.add_argument("--module-id", help="XRobot YAML 中要读取的模块 id/name / Module id/name to read from XRobot YAML")
    gen.add_argument("-o", "--output", type=Path, help="生成模块输出目录 / Generated module output directory")
    gen.add_argument("--module-name", help="XRobot 模块名 / XRobot module name")
    gen.add_argument("--class-name", help="生成的 XRobot Application 类名 / Generated XRobot Application class name")
    gen.add_argument("--root-namespace", help="生成 DSDL 类型使用的 C++ 命名空间 / C++ namespace for generated DSDL types")
    gen.add_argument("--node-name", help="默认 DroneCAN 节点名 / Default DroneCAN node name")
    gen.add_argument("--node-id", type=int, help="manifest 中的默认节点 ID / Default node ID in the manifest")
    gen.add_argument("--node-status-period-ms", type=int, help="默认 NodeStatus 周期 / Default NodeStatus period")
    gen.add_argument("--core-module-id", help="dronecan_core 的完整 XRobot 模块 ID / Full XRobot module ID for dronecan_core")
    return parser


def _as_dict(value: Any, context: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a YAML mapping")
    return value


def _as_list(value: Any, context: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a YAML list")
    return value


def _string_list(value: Any, context: str) -> list[str]:
    items = _as_list(value, context)
    if not all(isinstance(item, str) and item for item in items):
        raise ValueError(f"{context} must contain non-empty strings")
    return list(items)


def _path_list(value: Any, base: Path, context: str) -> list[Path]:
    paths = []
    for item in _string_list(value, context):
        path = Path(item)
        paths.append(path if path.is_absolute() else base / path)
    return paths


def _load_project_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _as_dict(data, str(path))


def _find_module(project: dict[str, Any], module_id: str | None) -> dict[str, Any]:
    modules = _as_list(project.get("modules"), "modules")
    if not modules:
        raise ValueError("XRobot YAML does not contain any modules")

    if module_id is None:
        if len(modules) != 1:
            raise ValueError("--module-id is required when XRobot YAML contains more than one module")
        selected = modules[0]
    else:
        selected = None
        for module in modules:
            if isinstance(module, dict) and module_id in (module.get("id"), module.get("name")):
                selected = module
                break
        if selected is None:
            raise ValueError(f"Module {module_id!r} was not found in XRobot YAML")

    return _as_dict(selected, "module entry")


def _parse_uint_literal(value: Any, context: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{context} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.endswith(("U", "u", "L", "l")):
            text = text.rstrip("UuLl")
        return int(text, 0)
    raise ValueError(f"{context} must be an integer")


def _resolve_value(value: Any, project: dict[str, Any], context: str) -> Any:
    if not isinstance(value, dict) or "constexpr" not in value:
        return value

    constexpr_name = value["constexpr"]
    constexprs = _as_dict(project.get("constexprs"), "constexprs")
    constexpr = _as_dict(constexprs.get(constexpr_name), f"constexprs.{constexpr_name}")
    resolved = constexpr.get("value")
    if isinstance(resolved, dict) and "expr" in resolved:
        return resolved["expr"]
    if resolved is None:
        raise ValueError(f"{context} references constexpr {constexpr_name!r} without a value")
    return resolved


def _constructor_value(module: dict[str, Any], project: dict[str, Any], name: str) -> Any:
    constructor_args = _as_dict(module.get("constructor_args"), "constructor_args")
    if name not in constructor_args:
        return None
    return _resolve_value(constructor_args[name], project, f"constructor_args.{name}")


def _project_root_from_yaml(path: Path) -> Path:
    if path.parent.name.lower() in ("user", "users"):
        return path.parent.parent
    return path.parent


def _resolve_path(value: Any, base: Path, context: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    path = Path(value)
    return path if path.is_absolute() else base / path


def _load_standalone_config(args: argparse.Namespace) -> dict[str, Any]:
    if args.config is None:
        return {}

    config_path = args.config.resolve()
    data = _load_project_yaml(config_path)
    root = _as_dict(data.get("dronecan"), "dronecan")
    module_cfg = _as_dict(root.get("module"), "dronecan.module")
    node_cfg = _as_dict(root.get("node"), "dronecan.node")
    dsdl_cfg = _as_dict(root.get("dsdl"), "dronecan.dsdl")
    base = _project_root_from_yaml(config_path)

    module_name = module_cfg.get("name")
    if module_name is not None and (not isinstance(module_name, str) or not module_name):
        raise ValueError("dronecan.module.name must be a non-empty string")

    source_dirs = _path_list(dsdl_cfg.get("source_dirs"), base, "dronecan.dsdl.source_dirs")
    include_builtin = dsdl_cfg.get("builtin")
    if include_builtin is None:
        include_builtin = not source_dirs

    return {
        "source_dirs": source_dirs,
        "lookup_dirs": _path_list(dsdl_cfg.get("lookup_dirs"), base, "dronecan.dsdl.lookup_dirs"),
        "include_builtin": bool(include_builtin),
        "types": _string_list(dsdl_cfg.get("types"), "dronecan.dsdl.types"),
        "output": _resolve_path(module_cfg.get("output"), base, "dronecan.module.output"),
        "module_name": module_name,
        "class_name": module_cfg.get("class_name"),
        "root_namespace": module_cfg.get("root_namespace"),
        "core_module_id": module_cfg.get("core_module_id"),
        "node_id": (
            _parse_uint_literal(node_cfg.get("default_node_id"), "dronecan.node.default_node_id")
            if node_cfg.get("default_node_id") is not None
            else None
        ),
        "node_status_period_ms": (
            _parse_uint_literal(node_cfg.get("node_status_period_ms"), "dronecan.node.node_status_period_ms")
            if node_cfg.get("node_status_period_ms") is not None
            else None
        ),
        "can_alias": node_cfg.get("can_alias") if isinstance(node_cfg.get("can_alias"), str) else None,
        "timebase_alias": node_cfg.get("timebase_alias") if isinstance(node_cfg.get("timebase_alias"), str) else None,
        "node_name": node_cfg.get("node_name") if isinstance(node_cfg.get("node_name"), str) else None,
    }


def _load_yaml_generation(args: argparse.Namespace) -> dict[str, Any]:
    if args.xrobot_yaml is None:
        return {}

    yaml_path = args.xrobot_yaml.resolve()
    project = _load_project_yaml(yaml_path)
    module = _find_module(project, args.module_id)
    generator = _as_dict(module.get("generator"), "module.generator")
    dsdl_cfg = _as_dict(generator.get("dsdl"), "module.generator.dsdl")
    project_root = _project_root_from_yaml(yaml_path)
    base = project_root
    module_name = module.get("name") or module.get("id")
    if not isinstance(module_name, str) or not module_name:
        raise ValueError("module name/id must be a non-empty string")

    output_value = dsdl_cfg.get("output")
    output = None
    if isinstance(output_value, str) and output_value:
        output_path = Path(output_value)
        output = output_path if output_path.is_absolute() else base / output_path
    else:
        output = project_root / "Modules" / module_name

    node_id = _constructor_value(module, project, "node_id")
    node_status_period_ms = _constructor_value(module, project, "node_status_period_ms")
    node_name = _constructor_value(module, project, "node_name")
    can_alias = _constructor_value(module, project, "can_alias")
    timebase_alias = _constructor_value(module, project, "timebase_alias")
    source_dirs = _path_list(dsdl_cfg.get("source_dirs"), base, "module.generator.dsdl.source_dirs")
    include_builtin = dsdl_cfg.get("builtin")
    if include_builtin is None:
        include_builtin = not source_dirs

    cfg: dict[str, Any] = {
        "source_dirs": source_dirs,
        "lookup_dirs": _path_list(dsdl_cfg.get("lookup_dirs"), base, "module.generator.dsdl.lookup_dirs"),
        "include_builtin": bool(include_builtin),
        "types": _string_list(dsdl_cfg.get("types"), "module.generator.dsdl.types"),
        "output": output,
        "module_name": module_name,
        "class_name": dsdl_cfg.get("class_name"),
        "root_namespace": dsdl_cfg.get("root_namespace"),
        "core_module_id": dsdl_cfg.get("core_module_id"),
        "node_id": _parse_uint_literal(node_id, "constructor_args.node_id") if node_id is not None else None,
        "node_status_period_ms": (
            _parse_uint_literal(node_status_period_ms, "constructor_args.node_status_period_ms")
            if node_status_period_ms is not None
            else None
        ),
        "can_alias": can_alias if isinstance(can_alias, str) else None,
        "timebase_alias": timebase_alias if isinstance(timebase_alias, str) else None,
        "node_name": node_name if isinstance(node_name, str) else None,
    }
    return cfg


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        if args.config is not None and args.xrobot_yaml is not None:
            raise ValueError("--config and --xrobot-yaml are mutually exclusive")

        yaml_cfg = _load_standalone_config(args) if args.config is not None else _load_yaml_generation(args)
        source_dirs = list(yaml_cfg.get("source_dirs", [])) + list(args.dsdl_dir)
        lookup_dirs = list(yaml_cfg.get("lookup_dirs", [])) + list(args.lookup_dir)
        include_builtin = args.builtin_dsdl or bool(yaml_cfg.get("include_builtin", False))
        requested_types = args.type if args.type is not None else yaml_cfg.get("types") or ["uavcan.protocol.NodeStatus"]
        module_name = args.module_name or yaml_cfg.get("module_name") or "dronecan_generated"
        output = args.output or yaml_cfg.get("output")
        if output is None:
            raise ValueError("--output is required unless --xrobot-yaml provides or implies an output path")

        dsdl_set = load_dsdl(source_dirs, lookup_dirs, include_builtin=include_builtin)
        selected = dsdl_set.select_with_dependencies(requested_types)
        class_name = args.class_name or yaml_cfg.get("class_name") or default_class_name(module_name)
        cfg = GenerationConfig(
            output=output,
            module_name=module_name,
            class_name=class_name,
            root_namespace=args.root_namespace or yaml_cfg.get("root_namespace") or "DroneCANGenerated",
            node_name=args.node_name or yaml_cfg.get("node_name") or "org.libxr.dronecan.generated",
            default_can_alias=yaml_cfg.get("can_alias") or "can0",
            default_timebase_alias=yaml_cfg.get("timebase_alias") or "timebase",
            default_node_id=args.node_id or yaml_cfg.get("node_id") or 10,
            default_node_status_period_ms=args.node_status_period_ms or yaml_cfg.get("node_status_period_ms") or 1000,
            core_module_id=args.core_module_id or yaml_cfg.get("core_module_id") or "CaFeZn/dronecan_core",
        )
        generate_module(cfg, selected)
        print(f"[OK] 已生成 {cfg.module_name}: {cfg.output} / Generated {cfg.module_name} at {cfg.output}")
        print(f"[OK] 已输出 {len(selected)} 个 DSDL 类型 / Emitted {len(selected)} DSDL type(s)")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
