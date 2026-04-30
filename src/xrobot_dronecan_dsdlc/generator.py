"""从已解析的 DSDL 类型生成 XRobot/LibXR 模块仓库。

Generate XRobot/LibXR module repositories from parsed DSDL types.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml
from dronecan.dsdl import CompoundType

from .dsdl import compound_dependencies
from .cpp import CppTypeRenderer
from .naming import is_cpp_identifier, is_cpp_qualified_identifier, to_pascal, to_snake, type_alias_name

_MAX_NODE_NAME_BYTES = 80
_NODE_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")


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
class GenerationConfig:
    output: Path
    module_name: str
    class_name: str
    root_namespace: str
    node_name: str = "org.libxr.dronecan.generated"
    default_node_id: int = 10
    default_node_status_period_ms: int = 1000

    def __post_init__(self) -> None:
        if not is_cpp_identifier(self.module_name):
            raise ValueError(f"module_name must be a valid C++ identifier for XRobot: {self.module_name!r}")
        if not is_cpp_identifier(self.class_name):
            raise ValueError(f"class_name must be a valid C++ identifier: {self.class_name!r}")
        if not is_cpp_qualified_identifier(self.root_namespace):
            raise ValueError(f"root_namespace must be a valid C++ namespace identifier: {self.root_namespace!r}")
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


@dataclass(frozen=True)
class TransferSpec:
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
        out.mkdir(parents=True, exist_ok=True)

        self._write(out / "module.yaml", self.render_module_yaml())
        self._write(out / "CMakeLists.txt", self.render_cmake())
        self._write(out / "info.cmake", self.render_info_cmake())
        self._write(out / "README.md", self.render_readme())
        self._write(out / self.detail_header_name, self.render_detail_header())
        for compound in self.types:
            self._write(out / self.type_header_names[compound.full_name], self.render_type_header(compound))
        self._write(out / f"{self.cfg.module_name}.hpp", self.render_module_header())

    @staticmethod
    def _write(path: Path, text: str) -> None:
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
            if compound.kind == CompoundType.KIND_MESSAGE:
                specs.append(self._make_transfer_spec(compound, base_alias, None, "Message", "Publish"))
            else:
                specs.append(self._make_transfer_spec(compound, base_alias + "Request", "request", "Request", "Request"))
                specs.append(self._make_transfer_spec(compound, base_alias + "Response", "response", "Response", "Respond"))
        return specs

    def _make_transfer_spec(
        self,
        compound: CompoundType,
        alias: str,
        part: str | None,
        transfer_kind: str,
        method_prefix: str,
    ) -> TransferSpec:
        member = to_snake(alias)
        cpp_type = self.type_renderer.qualified_struct(compound, part)
        return TransferSpec(
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
            service_part=part,
        )

    def render_module_yaml(self) -> str:
        data = {
            "name": self.cfg.module_name,
            "class_name": self.cfg.class_name,
            "header": f"{self.cfg.module_name}.hpp",
            "constructor_args": {
                "node_id": self.cfg.default_node_id,
                "can_alias": "can0",
                "timebase_alias": "timebase",
                "node_name": self.cfg.node_name,
                "node_status_period_ms": self.cfg.default_node_status_period_ms,
            },
            "dsdl": [{"type": item.full_name} for item in self.types],
        }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def render_cmake(self) -> str:
        return """target_include_directories(xr PUBLIC
  ${CMAKE_CURRENT_LIST_DIR}
)
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

// clang-format off
{self.render_manifest()}
// clang-format on

{type_includes}

{self.render_application_class()}

{chr(10).join(alias_lines)}
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
        data = {
            "module_description": "由 DroneCAN DSDL 生成的 XRobot/LibXR 模块 / Generated XRobot/LibXR module from DroneCAN DSDL",
            "constructor_args": [
                {"node_id": self.cfg.default_node_id},
                {"can_alias": "can0"},
                {"timebase_alias": "timebase"},
                {"node_name": self.cfg.node_name},
                {"node_status_period_ms": self.cfg.default_node_status_period_ms},
            ],
            "template_args": [],
            "required_hardware": "can0 timebase",
            "depends": ["dronecan_core"],
        }
        manifest = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip()
        return f"/* === MODULE MANIFEST V2 ===\n{manifest}\n=== END MANIFEST === */"

    def render_readme(self) -> str:
        type_list = "\n".join(f"- `{item.full_name}`" for item in self.types)
        type_file_list = "\n".join(
            f"- `{self.type_header_names[item.full_name]}`: `{item.full_name}`" for item in self.types
        )
        example_yaml = yaml.safe_dump(
            {
                "modules": [
                    {
                        "id": self.cfg.module_name,
                        "name": self.cfg.module_name,
                        "constructor_args": {
                            "node_id": self.cfg.default_node_id,
                            "can_alias": "can0",
                            "timebase_alias": "timebase",
                            "node_name": self.cfg.node_name,
                            "node_status_period_ms": self.cfg.default_node_status_period_ms,
                        },
                    }
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ).rstrip()
        return f"""# {self.cfg.module_name}

已生成的 XRobot/LibXR DroneCAN 模块。

Generated XRobot/LibXR DroneCAN module.

## DSDL 类型 / DSDL Types

{type_list}

## 模块布局 / Module Layout

- `{self.cfg.module_name}.hpp`: 单文件 XRobot Application facade，包含 manifest、模块运行逻辑和 using 别名。
- `{self.cfg.module_name}.hpp`: single-file XRobot Application facade with manifest, runtime logic, and using aliases.
- `{self.detail_header_name}`: DSDL 编解码公共 helper。
- `{self.detail_header_name}`: shared helpers for generated DSDL codecs.

## DSDL Headers

{type_file_list}

## XRobot 示例 / XRobot Example

```yaml
{example_yaml}
```

该模块持有一个 `DroneCANCoreSupport::DroneCANNode`，通过 `OnMonitor()` 轮询，
并暴露类型化的发布、请求、响应方法，以及可选的接收传输回调。

The module owns a `DroneCANCoreSupport::DroneCANNode`, polls it from
`OnMonitor()`, and exposes typed publish/request/respond methods plus optional
callbacks for received transfers.
"""

    def render_application_class(self) -> str:
        callback_lines = []
        public_method_lines = []
        private_method_lines = []
        member_lines = []
        for spec in self.transfers:
            callback_lines.append(
                f"  using {spec.callback_type} = void (*)(void*, const LibXR::DroneCAN::TransferMetadata&, const {spec.cpp_type}&);"
            )
            public_method_lines.append(self._render_setter_method(spec))
            public_method_lines.append(self._render_send_method(spec))
            private_method_lines.append(self._render_transfer_methods(spec))
            member_lines.extend(
                [
                    f"  LibXR::DroneCAN::TransferHandler {spec.handler_member};",
                    f"  void* {spec.callback_context_member} = nullptr;",
                    f"  {spec.callback_type} {spec.callback_member} = nullptr;",
                ]
            )

        init_handlers = "".join(
            f",\n        {spec.handler_member}(LibXR::DroneCAN::TransferHandler::Create({spec.static_handler}, this))"
            for spec in self.transfers
        )
        registrations = "\n".join(
            f"    (void)node_.RegisterTransferHandler(LibXR::DroneCAN::TransferKind::{spec.transfer_kind}, {spec.data_type_id_owner}::kDataTypeId, {spec.data_type_id_owner}::kDataTypeSignature, {spec.handler_member});"
            for spec in self.transfers
        )

        return f"""#include <array>
#include <cstdint>
#include <cstring>

extern "C"
{{
#include "canard.h"
}}

#include "app_framework.hpp"
#include "can.hpp"
#include "dronecan_core/DroneCANNode.hpp"
#include "dronecan_core/dronecan_types.hpp"
#include "libxr.hpp"
#include "timebase.hpp"

class {self.cfg.class_name} final : public LibXR::Application
{{
 public:
{chr(10).join(callback_lines) if callback_lines else "  // 未选择默认数据类型 ID，因此不会生成传输处理器。 / No default data type IDs were selected; no transfer handlers are generated."}

  {self.cfg.class_name}(LibXR::HardwareContainer& hw,
                        LibXR::ApplicationManager& appmgr,
                        std::uint8_t node_id = {self.cfg.default_node_id}U,
                        const char* can_alias = "can0",
                        const char* timebase_alias = "timebase",
                        const char* node_name = {_cpp_string_literal(self.cfg.node_name)},
                        std::uint32_t node_status_period_ms = {self.cfg.default_node_status_period_ms}U)
      : can_(*hw.FindOrExit<LibXR::CAN>({{NormalizeCString(can_alias, "can0")}})),
        timebase_(*hw.FindOrExit<LibXR::Timebase>({{NormalizeCString(timebase_alias, "timebase")}})),
        node_(can_, timebase_, node_arena_.data(), node_arena_.size(), MakeNodeConfig(node_status_period_ms)){init_handlers}
  {{
    (void)node_.SetNodeID(node_id);
    node_.SetNodeInfo(MakeNodeInfo(NormalizeCString(node_name, {_cpp_string_literal(self.cfg.node_name)})));
    node_.SetNodeStatusMode(LibXR::DroneCAN::NodeMode::OPERATIONAL);
{registrations}
    appmgr.Register(*this);
  }}

  void OnMonitor() override
  {{
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

{chr(10).join(public_method_lines)}

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

{chr(10).join(private_method_lines)}

  LibXR::CAN& can_;
  LibXR::Timebase& timebase_;
  std::array<std::uint8_t, kNodeArenaSize> node_arena_{{}};
  DroneCANCoreSupport::DroneCANNode node_;
{chr(10).join(member_lines)}
}};"""

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

    if ({spec.callback_member} != nullptr)
    {{
      {spec.callback_member}({spec.callback_context_member}, meta, decoded);
    }}
  }}
"""

def generate_module(cfg: GenerationConfig, types: Iterable[CompoundType]) -> None:
    ModuleRenderer(cfg, types).write()
