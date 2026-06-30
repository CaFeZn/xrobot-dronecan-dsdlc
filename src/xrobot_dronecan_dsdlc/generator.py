"""从已解析的 DSDL 类型生成 XRobot/LibXR 模块仓库。

Generate XRobot/LibXR module repositories from parsed DSDL types.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml
from dronecan.dsdl import CompoundType

from .dsdl import compound_dependencies
from .cpp import CppTypeRenderer
from .naming import is_cpp_identifier, is_cpp_qualified_identifier, to_pascal, to_snake, type_alias_name

_MAX_NODE_NAME_BYTES = 80
_NODE_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")
_ALIAS_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
_GENERATED_DIR_NAME = "generated"
_MODE_FACADE_OWN_NODE = "facade-own-node"
_MODE_BINDING_ONLY = "binding-only"
_VALID_MODES = frozenset({_MODE_FACADE_OWN_NODE, _MODE_BINDING_ONLY})


def _cpp_string_literal(value: str) -> str:
    escapes = {
        "\\": "\\\\",
        '"': '\\"',
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\b": "\\b",
        "\f": "\\f",
        "\v": "\\v",
    }
    escaped = "".join(escapes.get(ch, f"\\{ord(ch):03o}" if ord(ch) < 32 or ord(ch) == 127 else ch) for ch in value)
    return f'"{escaped}"'


@dataclass(frozen=True)
class TypeGenerationOptions:
    full_name: str
    message_rx: bool = True
    message_tx: bool = True
    message_callback: bool = True
    message_topic: bool = False
    service_server: bool = True
    service_client: bool = True
    service_callback: bool = True


@dataclass(frozen=True)
class GenerationConfig:
    output: Path
    module_name: str
    class_name: str
    root_namespace: str
    mode: str = _MODE_FACADE_OWN_NODE
    node_name: str = "org.libxr.dronecan.generated"
    default_can_alias: str = "can0"
    default_timebase_alias: str = "timebase"
    default_node_id: int = 10
    default_node_status_period_ms: int = 1000
    core_module_id: str = "CaFeZn/dronecan_core"
    type_options: Mapping[str, TypeGenerationOptions] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not is_cpp_identifier(self.module_name):
            raise ValueError(f"module_name must be a valid C++ identifier for XRobot: {self.module_name!r}")
        if not is_cpp_identifier(self.class_name):
            raise ValueError(f"class_name must be a valid C++ identifier: {self.class_name!r}")
        if not is_cpp_qualified_identifier(self.root_namespace):
            raise ValueError(f"root_namespace must be a valid C++ namespace identifier: {self.root_namespace!r}")
        if self.mode not in _VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(_VALID_MODES)!r}: {self.mode!r}")
        if self.output.name != self.module_name:
            raise ValueError(
                "output directory name must match module_name for XRobot discovery: "
                f"{self.output.name!r} != {self.module_name!r}"
            )
        if not 1 <= self.default_node_id <= 127:
            raise ValueError(f"default_node_id must be in DroneCAN node ID range 1..127: {self.default_node_id!r}")
        if not 1 <= self.default_node_status_period_ms <= 0xFFFFFFFF:
            raise ValueError(
                "default_node_status_period_ms must fit uint32_t and be positive: "
                f"{self.default_node_status_period_ms!r}"
            )
        if not self.node_name:
            raise ValueError("node_name must not be empty")
        if any(ch not in _NODE_NAME_CHARS for ch in self.node_name):
            raise ValueError("node_name may only contain ASCII letters, digits, underscore, dot, and dash")
        if len(self.node_name.encode("utf-8")) > _MAX_NODE_NAME_BYTES:
            raise ValueError(f"node_name must be at most {_MAX_NODE_NAME_BYTES} UTF-8 bytes")
        for field_name, alias in (
            ("default_can_alias", self.default_can_alias),
            ("default_timebase_alias", self.default_timebase_alias),
        ):
            if not alias:
                raise ValueError(f"{field_name} must not be empty")
            if any(ch not in _ALIAS_CHARS for ch in alias):
                raise ValueError(f"{field_name} may only contain ASCII letters, digits, underscore, and dash")
        if not self.core_module_id or "/" not in self.core_module_id:
            raise ValueError("core_module_id must be a full XRobot module ID such as 'CaFeZn/dronecan_core'")


@dataclass(frozen=True)
class TransferSpec:
    full_name: str
    alias: str
    member: str
    callback_type: str
    callback_member: str
    callback_context_member: str
    handler_member: str
    static_handler: str
    instance_handler: str
    cpp_type: str
    data_type_id_owner: str
    transfer_kind: str
    send_method: str
    rx: bool
    tx: bool
    callback: bool
    topic: bool = False
    service_part: str | None = None


class ModuleRenderer:
    def __init__(self, cfg: GenerationConfig, types: Iterable[CompoundType]):
        self.cfg = cfg
        self.types = list(types)
        self.type_renderer = CppTypeRenderer(cfg.root_namespace, self.types)
        self.detail_header_name = f"{self.cfg.module_name}_dsdl_detail.hpp"
        self.type_header_names = {compound.full_name: self._type_header_name(compound) for compound in self.types}
        self.transfers = self._build_transfer_specs()

    def write(self) -> None:
        out = self.cfg.output
        generated = out / _GENERATED_DIR_NAME
        out.mkdir(parents=True, exist_ok=True)
        generated.mkdir(parents=True, exist_ok=True)

        self._write(out / ".gitignore", self.render_gitignore())
        self._write(out / "CMakeLists.txt", self.render_cmake())
        self._write(out / "info.cmake", self.render_info_cmake())
        readme = out / "README.md"
        if not readme.exists():
            self._write(readme, self.render_readme())
        self._write(generated / self.detail_header_name, self.render_detail_header())
        for compound in self.types:
            self._write(generated / self.type_header_names[compound.full_name], self.render_type_header(compound))
        self._write(generated / f"{self.cfg.module_name}.hpp", self.render_module_header())
        self._write(out / f"{self.cfg.module_name}.hpp", self.render_root_header())

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    @staticmethod
    def _type_header_name(compound: CompoundType) -> str:
        return f"{to_snake(type_alias_name(compound.full_name))}.hpp"

    def _build_transfer_specs(self) -> list[TransferSpec]:
        specs: list[TransferSpec] = []
        for compound in self.types:
            if compound.default_dtid is None:
                continue
            base_alias = type_alias_name(compound.full_name)
            options = self.cfg.type_options.get(compound.full_name, TypeGenerationOptions(compound.full_name))
            if compound.kind == CompoundType.KIND_MESSAGE:
                if options.message_rx or options.message_tx or options.message_topic:
                    specs.append(
                        self._make_transfer_spec(
                            compound,
                            base_alias,
                            None,
                            "Message",
                            "Publish",
                            rx=options.message_rx,
                            tx=options.message_tx,
                            callback=options.message_rx and options.message_callback,
                            topic=options.message_topic,
                        )
                    )
            else:
                if options.service_server or options.service_client:
                    specs.append(
                        self._make_transfer_spec(
                            compound,
                            base_alias + "Request",
                            "request",
                            "Request",
                            "Request",
                            rx=options.service_server,
                            tx=options.service_client,
                            callback=options.service_server and options.service_callback,
                        )
                    )
                    specs.append(
                        self._make_transfer_spec(
                            compound,
                            base_alias + "Response",
                            "response",
                            "Response",
                            "Respond",
                            rx=options.service_client,
                            tx=options.service_server,
                            callback=options.service_client and options.service_callback,
                        )
                    )
        return specs

    def _make_transfer_spec(
        self,
        compound: CompoundType,
        alias: str,
        part: str | None,
        transfer_kind: str,
        method_prefix: str,
        *,
        rx: bool,
        tx: bool,
        callback: bool,
        topic: bool = False,
    ) -> TransferSpec:
        member = to_snake(alias)
        cpp_type = self.type_renderer.qualified_struct(compound, part)
        return TransferSpec(
            full_name=compound.full_name,
            alias=alias,
            member=member,
            callback_type=f"{alias}Callback",
            callback_member=f"{member}_callback_",
            callback_context_member=f"{member}_context_",
            handler_member=f"{member}_handler_",
            static_handler=f"On{alias}TransferStatic",
            instance_handler=f"On{alias}Transfer",
            cpp_type=cpp_type,
            data_type_id_owner=cpp_type,
            transfer_kind=transfer_kind,
            send_method=f"{method_prefix}{alias}",
            rx=rx,
            tx=tx,
            callback=callback,
            topic=topic,
            service_part=part,
        )

    def render_cmake(self) -> str:
        return """target_include_directories(xr PUBLIC
  ${CMAKE_CURRENT_LIST_DIR}
  ${CMAKE_CURRENT_LIST_DIR}/generated
)
"""

    @staticmethod
    def render_gitignore() -> str:
        return """# Generated by the DroneCAN DSDL generator for each consuming project.
/generated/
"""

    def render_info_cmake(self) -> str:
        return f"# 已生成的 DroneCAN DSDL XRobot 模块 / Generated DroneCAN DSDL XRobot module: {self.cfg.module_name}\n"

    def render_module_header(self) -> str:
        pascal_alias = to_pascal(self.cfg.module_name)
        alias_lines = []
        for alias in (self.cfg.module_name, pascal_alias):
            if alias != self.cfg.class_name and alias not in alias_lines:
                alias_lines.append(f"using {alias} = {self.cfg.class_name};")
        type_includes = "\n".join(
            f'#include "{self.type_header_names[item.full_name]}"' for item in self.types
        )
        return f"""#pragma once

{type_includes}

{self.render_application_class()}

{chr(10).join(alias_lines)}
"""

    def render_root_header(self) -> str:
        return f"""#pragma once

// clang-format off
{self.render_manifest()}
// clang-format on

// Stable XRobot module entry. Generated implementation lives under `{_GENERATED_DIR_NAME}/`.
#include "{_GENERATED_DIR_NAME}/{self.cfg.module_name}.hpp"
"""

    def render_detail_header(self) -> str:
        return self.type_renderer.render_detail_header()

    def render_type_header(self, compound: CompoundType) -> str:
        includes = [self.detail_header_name]
        for dep in compound_dependencies(compound):
            header = self.type_header_names.get(dep.full_name)
            if header is None:
                raise ValueError(f"DSDL dependency was not selected for generation: {dep.full_name}")
            if header not in includes:
                includes.append(header)
        return self.type_renderer.render_compound_header(compound, includes)

    def render_manifest(self) -> str:
        if self.cfg.mode == _MODE_BINDING_ONLY:
            description = (
                "DroneCAN DSDL binding. The generated class attaches typed DSDL "
                "handlers and publish/request/respond wrappers to an external "
                "DroneCANNode owned by dronecan_core."
            )
            data = {
                "module_description": description,
                "constructor_args": [{"node": "@dronecan_core"}],
                "template_args": [],
                "required_hardware": "",
                "depends": [self.cfg.core_module_id],
            }
        else:
            data = {
                "module_description": (
                    "DroneCAN DSDL facade. Default instance configures the base node "
                    "and publishes uavcan.protocol.NodeStatus; project-specific DSDL "
                    "handlers are generated separately and runtime values live in "
                    "User/xrobot.yaml."
                ),
                "constructor_args": [
                    {"node_id": self.cfg.default_node_id},
                    {"can_alias": self.cfg.default_can_alias},
                    {"timebase_alias": self.cfg.default_timebase_alias},
                    {"node_name": self.cfg.node_name},
                    {"node_status_period_ms": self.cfg.default_node_status_period_ms},
                ],
                "template_args": [],
                "required_hardware": f"{self.cfg.default_can_alias} {self.cfg.default_timebase_alias}",
                "depends": [self.cfg.core_module_id],
            }
        manifest = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip()
        return f"/* === MODULE MANIFEST V2 ===\n{manifest}\n=== END MANIFEST === */"

    def render_readme(self) -> str:
        type_list = "\n".join(f"- `{item.full_name}`" for item in self.types)
        type_file_list = "\n".join(
            f"- `{self.type_header_names[item.full_name]}`: `{item.full_name}`" for item in self.types
        )
        if self.cfg.mode == _MODE_BINDING_ONLY:
            example = {
                "modules": [
                    {
                        "id": "dronecan_core",
                        "name": "DroneCANCoreModule",
                        "constructor_args": {
                            "node_id": self.cfg.default_node_id,
                            "can_alias": self.cfg.default_can_alias,
                            "timebase_alias": self.cfg.default_timebase_alias,
                            "node_name": self.cfg.node_name,
                            "node_status_period_ms": self.cfg.default_node_status_period_ms,
                        },
                    },
                    {
                        "id": self.cfg.module_name,
                        "name": self.cfg.module_name,
                        "constructor_args": {"node": "@dronecan_core"},
                    },
                ]
            }
            generated_header_description = "生成的 binding-only DSDL 适配层，接收外部 DroneCANNode。"
            generated_header_description_en = "generated binding-only DSDL adapter that accepts an external DroneCANNode."
            instantiation_description = (
                "在 `User/xrobot.yaml` 中先实例化共享的 `dronecan_core` runtime，再把外部 node 注入生成的 binding。"
            )
            instantiation_description_en = (
                "Instantiate the shared `dronecan_core` runtime first in `User/xrobot.yaml`, then inject its node into the generated binding."
            )
            runtime_description = (
                "该模块不持有 CAN、Timebase、arena 或 DroneCANNode；它只在外部 node 上注册 handler，并暴露类型化的发布、请求和响应方法。"
            )
            runtime_description_en = (
                "The module does not own CAN, Timebase, an arena, or a DroneCANNode; it only registers handlers on an external node and exposes typed publish/request/respond methods."
            )
        else:
            example = {
                "modules": [
                    {
                        "id": self.cfg.module_name,
                        "name": self.cfg.module_name,
                        "constructor_args": {
                            "node_id": self.cfg.default_node_id,
                            "can_alias": self.cfg.default_can_alias,
                            "timebase_alias": self.cfg.default_timebase_alias,
                            "node_name": self.cfg.node_name,
                            "node_status_period_ms": self.cfg.default_node_status_period_ms,
                        },
                    }
                ]
            }
            generated_header_description = "生成的 XRobot Application facade，包含模块运行逻辑和 using 别名。"
            generated_header_description_en = "generated XRobot Application facade with runtime logic and using aliases."
            instantiation_description = "在 `User/xrobot.yaml` 中实例化生成的 facade；`dronecan_core` 作为依赖由构建系统加入，不需要在这里单独实例化。"
            instantiation_description_en = "Instantiate the generated facade in `User/xrobot.yaml`. `dronecan_core` is added as a dependency by the build and does not need a separate entry here."
            runtime_description = "该模块持有一个 `DroneCANCoreSupport::DroneCANNode`，通过 `OnMonitor()` 轮询，并暴露类型化的发布、请求、响应方法，以及可选的接收传输回调。"
            runtime_description_en = "The module owns a `DroneCANCoreSupport::DroneCANNode`, polls it from `OnMonitor()`, and exposes typed publish/request/respond methods plus optional callbacks for received transfers."
        example_yaml = yaml.safe_dump(example, sort_keys=False, allow_unicode=True).rstrip()
        return f"""# {self.cfg.module_name}

已生成的 XRobot/LibXR DroneCAN 模块。

Generated XRobot/LibXR DroneCAN module.

## DSDL 类型 / DSDL Types

{type_list}

## 模块布局 / Module Layout

- `{self.cfg.module_name}.hpp`: 稳定 XRobot 模块入口，包含 `MODULE MANIFEST V2` 并转发到 `generated/{self.cfg.module_name}.hpp`。
- `{self.cfg.module_name}.hpp`: stable XRobot module entry with `MODULE MANIFEST V2`; it forwards to `generated/{self.cfg.module_name}.hpp`.
- `generated/{self.cfg.module_name}.hpp`: {generated_header_description}
- `generated/{self.cfg.module_name}.hpp`: {generated_header_description_en}
- `generated/{self.detail_header_name}`: DSDL 编解码公共 helper。
- `generated/{self.detail_header_name}`: shared helpers for generated DSDL codecs.
- `.gitignore`: 忽略项目本地重新生成的 `generated/` 目录。
- `.gitignore`: ignores the per-project regenerated `generated/` directory.

## DSDL Headers

{type_file_list}

XRobot 从根级 `{self.cfg.module_name}.hpp` 读取 `MODULE MANIFEST V2`。该模块不生成
`module.yaml`；所有项目相关的 DSDL 产物都在 `generated/` 子目录，通常不提交到模块仓库。

XRobot reads `MODULE MANIFEST V2` from the root `{self.cfg.module_name}.hpp`.
No `module.yaml` is generated. Project-specific DSDL artifacts are kept under
the `generated/` subdirectory and are usually not committed to the module repo.

## XRobot 实例化示例 / XRobot Instantiation Example

{instantiation_description}

{instantiation_description_en}

```yaml
{example_yaml}
```

## 自定义 DSDL / Custom DSDL

自定义 DSDL 时，把 DSDL 根命名空间目录作为 `generate` 的位置参数。
例如 `my_company.actuator.MyCommand` 对应的源文件通常放在：

```text
CustomDSDL/
  my_company/
    actuator/
      20000.MyCommand.uavcan
```

命令中应传入 `CustomDSDL/my_company`，并用 `--type my_company.actuator.MyCommand`
指定要生成的类型。如果自定义类型引用标准 `uavcan.*` 类型，保留 `--builtin-dsdl`。
如果有额外只用于依赖解析的 DSDL 根目录，可用 `-I` / `--lookup-dir` 添加。

```powershell
xr_dronecan_dsdlc generate `
  D:/Path/To/CustomDSDL/my_company `
  --builtin-dsdl `
  --type my_company.actuator.MyCommand `
  --module-name {self.cfg.module_name} `
  --class-name {self.cfg.class_name} `
  --root-namespace {self.cfg.root_namespace} `
  --core-module-id {self.cfg.core_module_id} `
  --output D:/Codes/DroneCAN/{self.cfg.module_name}
```

For custom DSDL, pass the root namespace directory to `generate`. The directory
above is passed as `CustomDSDL/my_company`, while the type is selected with
`--type my_company.actuator.MyCommand`. Keep `--builtin-dsdl` when standard
`uavcan.*` dependencies are referenced, and use `-I` / `--lookup-dir` for extra
dependency-only DSDL roots.

{runtime_description}

{runtime_description_en}
"""

    def render_application_class(self) -> str:
        type_alias_lines = []
        callback_lines = []
        topic_alias_lines = []
        topic_name_lines = []
        public_method_lines = []
        private_method_lines = []
        member_lines = []
        for compound in self.types:
            base_alias = type_alias_name(compound.full_name)
            if compound.kind == CompoundType.KIND_MESSAGE:
                type_alias_lines.append(f"  using {base_alias} = {self.type_renderer.qualified_struct(compound, None)};")
            else:
                type_alias_lines.append(
                    f"  using {base_alias}Request = {self.type_renderer.qualified_struct(compound, 'request')};"
                )
                type_alias_lines.append(
                    f"  using {base_alias}Response = {self.type_renderer.qualified_struct(compound, 'response')};"
                )
        for spec in self.transfers:
            if spec.callback:
                callback_lines.append(
                    f"  using {spec.callback_type} = void (*)(void*, const LibXR::DroneCAN::TransferMetadata&, const {spec.cpp_type}&);"
                )
                public_method_lines.append(self._render_setter_method(spec))
            if self._has_topic(spec):
                topic_alias_lines.append(f"  using {spec.alias}TopicData = LibXR::DroneCAN::TopicMessage<{spec.cpp_type}>;")
            if self._has_rx_topic(spec):
                topic_name_lines.append(
                    f"  static constexpr const char* k{spec.alias}TopicName = {_cpp_string_literal(self._rx_topic_name(spec))};"
                )
                public_method_lines.append(self._render_topic_accessor(spec, tx=False))
                member_lines.append(f"  LibXR::Topic {self._rx_topic_member(spec)};")
            if self._has_tx_topic(spec):
                topic_name_lines.append(
                    f"  static constexpr const char* k{spec.alias}TxTopicName = {_cpp_string_literal(self._tx_topic_name(spec))};"
                )
                public_method_lines.append(self._render_topic_accessor(spec, tx=True))
                private_method_lines.append(self._render_tx_topic_methods(spec))
                member_lines.extend(
                    [
                        f"  LibXR::Topic {self._tx_topic_member(spec)};",
                        f"  LibXR::Topic::Callback {self._tx_topic_callback_member(spec)};",
                    ]
                )
            if spec.tx:
                public_method_lines.append(self._render_send_method(spec))
            if spec.rx:
                private_method_lines.append(self._render_transfer_methods(spec))
                member_lines.append(f"  LibXR::DroneCAN::TransferHandler {spec.handler_member};")
            if spec.callback:
                member_lines.extend(
                    [
                        f"  void* {spec.callback_context_member} = nullptr;",
                        f"  {spec.callback_type} {spec.callback_member} = nullptr;",
                    ]
                )

        init_handlers = "".join(
            f",\n        {spec.handler_member}(LibXR::DroneCAN::TransferHandler::Create({spec.static_handler}, this))"
            for spec in self.transfers
            if spec.rx
        )
        init_topics = "".join(
            f",\n        {self._rx_topic_member(spec)}(LibXR::Topic::CreateTopic<{spec.alias}TopicData>(k{spec.alias}TopicName))"
            for spec in self.transfers
            if self._has_rx_topic(spec)
        )
        init_tx_topics = "".join(
            f",\n        {self._tx_topic_member(spec)}(LibXR::Topic::CreateTopic<{spec.alias}TopicData>(k{spec.alias}TxTopicName))"
            for spec in self.transfers
            if self._has_tx_topic(spec)
        )
        init_tx_callbacks = "".join(
            f",\n        {self._tx_topic_callback_member(spec)}(LibXR::Topic::Callback::Create({self._tx_topic_static_handler(spec)}, this))"
            for spec in self.transfers
            if self._has_tx_topic(spec)
        )
        registrations = "\n".join(
            f"    (void)node_.RegisterTransferHandler(LibXR::DroneCAN::TransferKind::{spec.transfer_kind}, {spec.data_type_id_owner}::kDataTypeId, {spec.data_type_id_owner}::kDataTypeSignature, {spec.handler_member});"
            for spec in self.transfers
            if spec.rx
        )
        tx_topic_registrations = "\n".join(
            f"    {self._tx_topic_member(spec)}.RegisterCallback({self._tx_topic_callback_member(spec)});"
            for spec in self.transfers
            if self._has_tx_topic(spec)
        )
        init_runtime_members = init_topics + init_tx_topics + init_handlers + init_tx_callbacks
        no_transfer_text = "  // 未选择默认数据类型 ID，因此不会生成传输处理器。 / No default data type IDs were selected; no transfer handlers are generated."
        callback_block = "\n".join(callback_lines + topic_alias_lines + [""] + topic_name_lines).rstrip() or no_transfer_text
        public_methods = "\n".join(line for line in public_method_lines if line)
        private_methods = "\n".join(line for line in private_method_lines if line)
        members = "\n".join(member_lines)

        if self.cfg.mode == _MODE_BINDING_ONLY:
            return f"""#include <array>
#include <cstdint>
#include <cstring>

extern "C"
{{
#include "canard.h"
}}

#include "dronecan_core/DroneCANNode.hpp"
#include "dronecan_core/dronecan_types.hpp"
#include "libxr.hpp"

class {self.cfg.class_name} final
{{
 public:
{chr(10).join(type_alias_lines)}

{callback_block}

  explicit {self.cfg.class_name}(DroneCANCoreSupport::DroneCANNode& node)
      : node_(node){init_runtime_members}
  {{
{registrations}
{tx_topic_registrations}
  }}

  DroneCANCoreSupport::DroneCANNode& Node() noexcept
  {{
    return node_;
  }}

  const DroneCANCoreSupport::DroneCANNode& Node() const noexcept
  {{
    return node_;
  }}

{public_methods}

 private:
  static std::uint8_t NormalizePriority(std::uint8_t priority) noexcept
  {{
    return (priority <= CANARD_TRANSFER_PRIORITY_LOWEST) ? priority : CANARD_TRANSFER_PRIORITY_MEDIUM;
  }}

{private_methods}

  DroneCANCoreSupport::DroneCANNode& node_;
{members}
}};"""

        return f"""#include <array>
#include <cstdio>
#include <cstdint>
#include <cstring>

extern "C"
{{
#include "canard.h"
}}

#include "app_framework.hpp"
#include "can.hpp"
#include "dronecan_core/CanPoller.hpp"
#include "dronecan_core/DroneCANNode.hpp"
#include "dronecan_core/dronecan_types.hpp"
#include "libxr.hpp"
#include "timebase.hpp"

class {self.cfg.class_name} final : public LibXR::Application
{{
 public:
{chr(10).join(type_alias_lines)}

{callback_block}

  {self.cfg.class_name}(LibXR::HardwareContainer& hw,
                        LibXR::ApplicationManager& appmgr,
                        std::uint8_t node_id = {self.cfg.default_node_id}U,
                        const char* can_alias = {_cpp_string_literal(self.cfg.default_can_alias)},
                        const char* timebase_alias = {_cpp_string_literal(self.cfg.default_timebase_alias)},
                        const char* node_name = {_cpp_string_literal(self.cfg.node_name)},
                        std::uint32_t node_status_period_ms = {self.cfg.default_node_status_period_ms}U)
      : can_(*hw.FindOrExit<LibXR::CAN>({{NormalizeCString(can_alias, {_cpp_string_literal(self.cfg.default_can_alias)})}})),
        timebase_(*hw.FindOrExit<LibXR::Timebase>({{NormalizeCString(timebase_alias, {_cpp_string_literal(self.cfg.default_timebase_alias)})}})),
        node_(can_, timebase_, node_arena_.data(), node_arena_.size(), MakeNodeConfig(node_status_period_ms)){init_runtime_members}
  {{
    char poller_alias[32]{{}};
    MakePollerAlias(NormalizeCString(can_alias, {_cpp_string_literal(self.cfg.default_can_alias)}), poller_alias, sizeof(poller_alias));
    can_poller_ = hw.Find<DroneCANCoreSupport::CanPoller>(
        {{poller_alias, "can_poller", "dronecan_poller", "can1_poller", "can0_poller"}});
    (void)node_.SetNodeID(node_id);
    node_.SetNodeInfo(MakeNodeInfo(NormalizeCString(node_name, {_cpp_string_literal(self.cfg.node_name)})));
    node_.SetNodeStatusMode(LibXR::DroneCAN::NodeMode::OPERATIONAL);
{registrations}
{tx_topic_registrations}
    appmgr.Register(*this);
  }}

  void OnMonitor() override
  {{
    if (can_poller_ != nullptr)
    {{
      can_poller_->Poll();
    }}
    node_.Poll();
  }}

  DroneCANCoreSupport::DroneCANNode& Node() noexcept
  {{
    return node_;
  }}

  const DroneCANCoreSupport::DroneCANNode& Node() const noexcept
  {{
    return node_;
  }}

{public_methods}

 private:
  static constexpr std::size_t kNodeArenaSize = 4096U;

  static const char* NormalizeCString(const char* value, const char* fallback) noexcept
  {{
    return (value != nullptr && value[0] != '\\0') ? value : fallback;
  }}

  static std::uint32_t NormalizePeriodMs(std::uint32_t period_ms) noexcept
  {{
    return period_ms == 0U ? 1U : period_ms;
  }}

  static std::uint8_t NormalizePriority(std::uint8_t priority) noexcept
  {{
    return (priority <= CANARD_TRANSFER_PRIORITY_LOWEST) ? priority : CANARD_TRANSFER_PRIORITY_MEDIUM;
  }}

  static void MakePollerAlias(const char* can_alias, char* out, std::size_t out_size) noexcept
  {{
    if ((out == nullptr) || (out_size == 0U))
    {{
      return;
    }}
    const char* normalized = NormalizeCString(can_alias, {_cpp_string_literal(self.cfg.default_can_alias)});
    (void)std::snprintf(out, out_size, "%s_poller", normalized);
    out[out_size - 1U] = '\\0';
  }}

  static LibXR::DroneCAN::Config MakeNodeConfig(std::uint32_t node_status_period_ms) noexcept
  {{
    LibXR::DroneCAN::Config config{{}};
    config.node_status_period_us = static_cast<std::uint64_t>(NormalizePeriodMs(node_status_period_ms)) * 1000ULL;
    return config;
  }}

  static LibXR::DroneCAN::NodeInfo MakeNodeInfo(const char* node_name)
  {{
    LibXR::DroneCAN::NodeInfo info{{}};
    const char* normalized = NormalizeCString(node_name, {_cpp_string_literal(self.cfg.node_name)});
    std::strncpy(info.name, normalized, LibXR::DroneCAN::MAX_NODE_NAME_LENGTH);
    info.name[LibXR::DroneCAN::MAX_NODE_NAME_LENGTH] = '\\0';
    return info;
  }}

{private_methods}

  LibXR::CAN& can_;
  LibXR::Timebase& timebase_;
  DroneCANCoreSupport::CanPoller* can_poller_ = nullptr;
  std::array<std::uint8_t, kNodeArenaSize> node_arena_{{}};
  DroneCANCoreSupport::DroneCANNode node_;
{members}
}};"""

    @staticmethod
    def _has_rx_topic(spec: TransferSpec) -> bool:
        return spec.transfer_kind == "Message" and spec.topic and spec.rx

    @staticmethod
    def _has_tx_topic(spec: TransferSpec) -> bool:
        return spec.transfer_kind == "Message" and spec.topic and spec.tx

    def _has_topic(self, spec: TransferSpec) -> bool:
        return self._has_rx_topic(spec) or self._has_tx_topic(spec)

    @staticmethod
    def _rx_topic_name(spec: TransferSpec) -> str:
        return "/dronecan/" + spec.full_name.replace(".", "/")

    @staticmethod
    def _tx_topic_name(spec: TransferSpec) -> str:
        return "/dronecan/tx/" + spec.full_name.replace(".", "/")

    @staticmethod
    def _rx_topic_member(spec: TransferSpec) -> str:
        return f"{spec.member}_topic_"

    @staticmethod
    def _tx_topic_member(spec: TransferSpec) -> str:
        return f"{spec.member}_tx_topic_"

    @staticmethod
    def _tx_topic_callback_member(spec: TransferSpec) -> str:
        return f"{spec.member}_tx_callback_"

    @staticmethod
    def _tx_topic_static_handler(spec: TransferSpec) -> str:
        return f"On{spec.alias}TxTopicStatic"

    @staticmethod
    def _tx_topic_instance_handler(spec: TransferSpec) -> str:
        return f"On{spec.alias}TxTopic"

    def _render_topic_accessor(self, spec: TransferSpec, *, tx: bool) -> str:
        suffix = "TxTopic" if tx else "Topic"
        member = self._tx_topic_member(spec) if tx else self._rx_topic_member(spec)
        return f"""  LibXR::Topic {spec.alias}{suffix}() const noexcept
  {{
    return {member};
  }}
"""

    def _render_setter_method(self, spec: TransferSpec) -> str:
        return f"""  void Set{spec.alias}Callback(void* context, {spec.callback_type} callback) noexcept
  {{
    {spec.callback_context_member} = context;
    {spec.callback_member} = callback;
  }}
"""

    def _render_send_method(self, spec: TransferSpec) -> str:
        if spec.transfer_kind == "Message":
            signature = f"LibXR::ErrorCode {spec.send_method}(const {spec.cpp_type}& message, std::uint8_t priority = CANARD_TRANSFER_PRIORITY_MEDIUM)"
            value_name = "message"
            call = f"node_.Broadcast({spec.cpp_type}::kDataTypeId, {spec.cpp_type}::kDataTypeSignature, priority, LibXR::ConstRawData(payload.data(), payload_size))"
        elif spec.transfer_kind == "Request":
            signature = f"LibXR::ErrorCode {spec.send_method}(std::uint8_t destination_node_id, const {spec.cpp_type}& request, std::uint8_t priority = CANARD_TRANSFER_PRIORITY_MEDIUM)"
            value_name = "request"
            call = f"node_.Request(destination_node_id, {spec.cpp_type}::kDataTypeId, {spec.cpp_type}::kDataTypeSignature, priority, LibXR::ConstRawData(payload.data(), payload_size))"
        else:
            signature = f"LibXR::ErrorCode {spec.send_method}(std::uint8_t destination_node_id, std::uint8_t transfer_id, const {spec.cpp_type}& response, std::uint8_t priority = CANARD_TRANSFER_PRIORITY_MEDIUM)"
            value_name = "response"
            call = f"node_.Respond(destination_node_id, {spec.cpp_type}::kDataTypeId, {spec.cpp_type}::kDataTypeSignature, transfer_id, priority, LibXR::ConstRawData(payload.data(), payload_size))"

        return f"""  {signature}
  {{
    std::array<std::uint8_t, {spec.cpp_type}::kMaxPayloadSize> payload{{}};
    const std::size_t payload_size = {spec.cpp_type}::Encode({value_name}, payload.data(), payload.size());
    return {call};
  }}
"""

    def _render_transfer_methods(self, spec: TransferSpec) -> str:
        topic_publish = ""
        if self._has_rx_topic(spec):
            topic_publish = f"""
    {spec.alias}TopicData topic_data{{meta, decoded}};
    {self._rx_topic_member(spec)}.Publish(topic_data);
"""
        callback_call = ""
        if spec.callback:
            callback_call = f"""
    if ({spec.callback_member} != nullptr)
    {{
      {spec.callback_member}({spec.callback_context_member}, meta, decoded);
    }}
"""
        return f"""  static void {spec.static_handler}(bool, {self.cfg.class_name}* self, const LibXR::DroneCAN::TransferMetadata& meta, LibXR::ConstRawData payload)
  {{
    if (self != nullptr)
    {{
      self->{spec.instance_handler}(meta, payload);
    }}
  }}

  void {spec.instance_handler}(const LibXR::DroneCAN::TransferMetadata& meta, LibXR::ConstRawData payload) noexcept
  {{
    CanardRxTransfer transfer{{}};
    transfer.payload_len = static_cast<std::uint16_t>(payload.size_);
    transfer.payload_head = static_cast<const std::uint8_t*>(payload.addr_);

    {spec.cpp_type} decoded{{}};
    if (!{spec.cpp_type}::Decode(transfer, decoded))
    {{
      return;
    }}
{topic_publish}{callback_call}
  }}
"""

    def _render_tx_topic_methods(self, spec: TransferSpec) -> str:
        return f"""  static void {self._tx_topic_static_handler(spec)}(bool, {self.cfg.class_name}* self, LibXR::RawData& data)
  {{
    if (self != nullptr)
    {{
      self->{self._tx_topic_instance_handler(spec)}(data);
    }}
  }}

  void {self._tx_topic_instance_handler(spec)}(LibXR::RawData& data) noexcept
  {{
    if ((data.addr_ == nullptr) || (data.size_ != sizeof({spec.alias}TopicData)))
    {{
      return;
    }}

    const auto& topic_data = *reinterpret_cast<const {spec.alias}TopicData*>(data.addr_);
    (void){spec.send_method}(topic_data.message, NormalizePriority(topic_data.metadata.priority));
  }}
"""

def generate_module(cfg: GenerationConfig, types: Iterable[CompoundType]) -> None:
    ModuleRenderer(cfg, types).write()
