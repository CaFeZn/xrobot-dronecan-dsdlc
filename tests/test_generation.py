from pathlib import Path

import pytest
import yaml

from xrobot_dronecan_dsdlc.cli import main
from xrobot_dronecan_dsdlc.dsdl import load_dsdl
from xrobot_dronecan_dsdlc.generator import GenerationConfig, generate_module


def _load_manifest(module_hpp: str) -> dict:
    start = "/* === MODULE MANIFEST V2 ===\n"
    end = "\n=== END MANIFEST === */"
    return yaml.safe_load(module_hpp.split(start, 1)[1].split(end, 1)[0])


def test_builtin_esc_signatures_match_dronecan_v0():
    dsdl_set = load_dsdl([], include_builtin=True)
    types = dsdl_set.by_name

    assert types["uavcan.equipment.esc.RawCommand"].default_dtid == 1030
    assert types["uavcan.equipment.esc.RawCommand"].get_data_type_signature() == 0x217F5C87D7EC951D

    assert types["uavcan.equipment.esc.Status"].default_dtid == 1034
    assert types["uavcan.equipment.esc.Status"].get_data_type_signature() == 0xA9AF28AEA2FBB254


def test_generate_xrobot_module_layout(tmp_path: Path):
    dsdl_set = load_dsdl([], include_builtin=True)
    selected = dsdl_set.select_with_dependencies(
        ["uavcan.equipment.esc.RawCommand", "uavcan.equipment.esc.Status"]
    )
    cfg = GenerationConfig(
        output=tmp_path / "dronecan_esc_generated",
        module_name="dronecan_esc_generated",
        class_name="DroneCANEscGenerated",
        root_namespace="DroneCANEscTypes",
    )

    generate_module(cfg, selected)

    out = cfg.output
    assert not (out / "module.yaml").exists()
    assert (out / ".gitignore").exists()
    assert (out / "CMakeLists.txt").exists()
    assert (out / "dronecan_esc_generated.hpp").exists()
    assert sorted(path.name for path in out.glob("*.hpp")) == [
        "dronecan_esc_generated.hpp",
    ]
    assert sorted(path.name for path in (out / "generated").glob("*.hpp")) == [
        "dronecan_esc_generated.hpp",
        "dronecan_esc_generated_dsdl_detail.hpp",
        "uavcan_equipment_esc_raw_command.hpp",
        "uavcan_equipment_esc_status.hpp",
    ]
    assert not list(out.rglob("*.cpp"))
    assert not (out / "DroneCANEscGenerated.hpp").exists()
    assert not (out / "include" / "dronecan_esc_generated" / "dronecan_esc_generated_types.hpp").exists()
    assert not (out / "include" / "dronecan_esc_generated" / "dronecan_esc_generated_generated.hpp").exists()

    gitignore = (out / ".gitignore").read_text(encoding="utf-8")
    assert "/generated/" in gitignore

    cmake = (out / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "target_include_directories(xr PUBLIC" in cmake
    assert "${CMAKE_CURRENT_LIST_DIR}" in cmake
    assert "${CMAKE_CURRENT_LIST_DIR}/generated" in cmake
    assert "target_sources" not in cmake
    assert ".cpp" not in cmake

    root_hpp = (out / "dronecan_esc_generated.hpp").read_text(encoding="utf-8")
    assert "/* === MODULE MANIFEST V2 ===" in root_hpp
    assert "constructor_args:" in root_hpp
    assert "- node_id: 10" in root_hpp
    assert "- can_alias: can0" in root_hpp
    assert "template_args: []" in root_hpp
    assert "required_hardware: can0 timebase" in root_hpp
    assert "depends:" in root_hpp
    assert "- CaFeZn/dronecan_core" in root_hpp
    assert "=== END MANIFEST === */" in root_hpp
    assert '#include "generated/dronecan_esc_generated.hpp"' in root_hpp

    module_hpp = (out / "generated" / "dronecan_esc_generated.hpp").read_text(encoding="utf-8")
    assert "/* === MODULE MANIFEST V2 ===" not in module_hpp
    assert "using UavcanEquipmentEscRawCommand = ::DroneCANEscTypes::uavcan::equipment::esc::RawCommand;" in module_hpp
    assert "using UavcanEquipmentEscStatus = ::DroneCANEscTypes::uavcan::equipment::esc::Status;" in module_hpp
    assert "using dronecan_esc_generated = DroneCANEscGenerated;" in module_hpp
    assert "inline DroneCANEscGenerated::DroneCANEscGenerated(" not in module_hpp
    assert "DroneCANEscGenerated(LibXR::HardwareContainer& hw," in module_hpp
    assert "void OnMonitor() override" in module_hpp
    assert '#include "uavcan_equipment_esc_raw_command.hpp"' in module_hpp
    assert '#include "uavcan_equipment_esc_status.hpp"' in module_hpp
    assert "struct RawCommand" not in module_hpp

    raw_command_hpp = (out / "generated" / "uavcan_equipment_esc_raw_command.hpp").read_text(encoding="utf-8")
    assert '#include "dronecan_esc_generated_dsdl_detail.hpp"' in raw_command_hpp
    assert "kDataTypeId = 1030U" in raw_command_hpp
    assert "0x217F5C87D7EC951DULL" in raw_command_hpp
    assert "std::array<std::int16_t, 20U> cmd" in raw_command_hpp


def test_cli_defaults_to_node_status_only(tmp_path: Path):
    out = tmp_path / "dronecan_default"

    result = main(
        [
            "generate",
            "--builtin-dsdl",
            "--module-name",
            "dronecan_default",
            "--class-name",
            "DroneCANDefault",
            "--root-namespace",
            "DroneCANDefaultTypes",
            "--output",
            str(out),
        ]
    )

    assert result == 0
    assert sorted(path.name for path in (out / "generated").glob("*.hpp")) == [
        "dronecan_default.hpp",
        "dronecan_default_dsdl_detail.hpp",
        "uavcan_protocol_node_status.hpp",
    ]
    root_hpp = (out / "dronecan_default.hpp").read_text(encoding="utf-8")
    module_hpp = (out / "generated" / "dronecan_default.hpp").read_text(encoding="utf-8")
    assert "/* === MODULE MANIFEST V2 ===" in root_hpp
    assert "/* === MODULE MANIFEST V2 ===" not in module_hpp
    assert "using dronecan_default = DroneCANDefault;" in module_hpp


def test_generation_rejects_invalid_cpp_names(tmp_path: Path):
    with pytest.raises(ValueError, match="module_name"):
        GenerationConfig(
            output=tmp_path / "dronecan-bad",
            module_name="dronecan-bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
        )

    with pytest.raises(ValueError, match="class_name"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="class",
            root_namespace="DroneCANBadTypes",
        )

    with pytest.raises(ValueError, match="root_namespace"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="DroneCANBad",
            root_namespace="DroneCAN-Bad",
        )

    with pytest.raises(ValueError, match="default_node_id"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
            default_node_id=128,
        )

    with pytest.raises(ValueError, match="module_name"):
        GenerationConfig(
            output=tmp_path / "__bad",
            module_name="__bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
        )


def test_generation_rejects_unsafe_xrobot_configuration(tmp_path: Path):
    with pytest.raises(ValueError, match="output directory name"):
        GenerationConfig(
            output=tmp_path / "folder_name",
            module_name="module_name",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
        )

    with pytest.raises(ValueError, match="default_node_status_period_ms"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
            default_node_status_period_ms=0,
        )

    with pytest.raises(ValueError, match="node_name"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
            node_name="org.libxr.bad*/comment",
        )

    with pytest.raises(ValueError, match="node_name"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
            node_name="org.libxr.bad\nname",
        )

    with pytest.raises(ValueError, match="node_name"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
            node_name='org.libxr."bad"',
        )

    with pytest.raises(ValueError, match="core_module_id"):
        GenerationConfig(
            output=tmp_path / "dronecan_bad",
            module_name="dronecan_bad",
            class_name="DroneCANBad",
            root_namespace="DroneCANBadTypes",
            core_module_id="dronecan_core",
        )


def test_generated_node_name_is_yaml_and_cpp_safe(tmp_path: Path):
    dsdl_set = load_dsdl([], include_builtin=True)
    selected = dsdl_set.select_with_dependencies(["uavcan.protocol.NodeStatus"])
    cfg = GenerationConfig(
        output=tmp_path / "dronecan_node_status",
        module_name="dronecan_node_status",
        class_name="DroneCANNodeStatus",
        root_namespace="DroneCANNodeStatusTypes",
        node_name="org.libxr.test-node_1",
    )

    generate_module(cfg, selected)

    root_hpp = (cfg.output / "dronecan_node_status.hpp").read_text(encoding="utf-8")
    module_hpp = (cfg.output / "generated" / "dronecan_node_status.hpp").read_text(encoding="utf-8")
    manifest = _load_manifest(root_hpp)
    constructor_args = {}
    for item in manifest["constructor_args"]:
        constructor_args.update(item)

    assert constructor_args["node_name"] == "org.libxr.test-node_1"
    assert 'const char* node_name = "org.libxr.test-node_1"' in module_hpp


def test_alias_collisions_are_not_emitted(tmp_path: Path):
    dsdl_set = load_dsdl([], include_builtin=True)
    selected = dsdl_set.select_with_dependencies(["uavcan.protocol.NodeStatus"])

    cfg = GenerationConfig(
        output=tmp_path / "foo",
        module_name="foo",
        class_name="Foo",
        root_namespace="FooTypes",
    )
    generate_module(cfg, selected)
    module_hpp = (cfg.output / "generated" / "foo.hpp").read_text(encoding="utf-8")

    assert "class Foo final" in module_hpp
    assert "using foo = Foo;" in module_hpp
    assert "using Foo = Foo;" not in module_hpp


def test_nested_compound_tao_and_bounds_generation(tmp_path: Path):
    dsdl_set = load_dsdl([], include_builtin=True)
    selected = dsdl_set.select_with_dependencies(["uavcan.protocol.GetNodeInfo"])
    cfg = GenerationConfig(
        output=tmp_path / "dronecan_get_node_info",
        module_name="dronecan_get_node_info",
        class_name="DroneCANGetNodeInfo",
        root_namespace="DroneCANGetNodeInfoTypes",
    )

    generate_module(cfg, selected)
    detail_hpp = (cfg.output / "generated" / "dronecan_get_node_info_dsdl_detail.hpp").read_text(encoding="utf-8")
    get_node_info_hpp = (cfg.output / "generated" / "uavcan_protocol_get_node_info.hpp").read_text(encoding="utf-8")

    assert "CanWriteBits(std::size_t buffer_size" in detail_hpp
    assert '#include "uavcan_protocol_hardware_version.hpp"' in get_node_info_hpp
    assert '#include "uavcan_protocol_software_version.hpp"' in get_node_info_hpp
    assert "HardwareVersion::EncodeTo(msg.hardware_version, buffer, buffer_size, bit_offset, false)" in get_node_info_hpp
    assert "HardwareVersion::DecodeFrom(transfer, bit_offset, out.hardware_version, false)" in get_node_info_hpp
    assert "SoftwareVersion::EncodeTo(msg.software_version, buffer, buffer_size, bit_offset, false)" in get_node_info_hpp
    assert "if (!detail::CanWriteBits(buffer_size, bit_offset" in get_node_info_hpp


def test_union_tag_and_service_tao_generation(tmp_path: Path):
    dsdl_set = load_dsdl([], include_builtin=True)
    selected = dsdl_set.select_with_dependencies(["uavcan.protocol.param.GetSet"])
    cfg = GenerationConfig(
        output=tmp_path / "dronecan_param_getset",
        module_name="dronecan_param_getset",
        class_name="DroneCANParamGetSet",
        root_namespace="DroneCANParamGetSetTypes",
    )

    generate_module(cfg, selected)
    getset_hpp = (cfg.output / "generated" / "uavcan_protocol_param_get_set.hpp").read_text(encoding="utf-8")
    value_hpp = (cfg.output / "generated" / "uavcan_protocol_param_value.hpp").read_text(encoding="utf-8")

    assert "if (msg.union_tag >" in value_hpp
    assert '#include "uavcan_protocol_param_value.hpp"' in getset_hpp
    assert "Value::EncodeTo(msg.value, buffer, buffer_size, bit_offset, false)" in getset_hpp
    assert "Value::DecodeFrom(transfer, bit_offset, out.value, false)" in getset_hpp


def test_generation_rejects_dsdl_cpp_identifier_conflicts(tmp_path: Path):
    field_root = tmp_path / "testns"
    field_root.mkdir()
    (field_root / "20000.BadField.uavcan").write_text("uint8 class\n", encoding="utf-8")
    field_set = load_dsdl([field_root])
    field_selected = field_set.select_with_dependencies(["testns.BadField"])
    field_cfg = GenerationConfig(
        output=tmp_path / "dronecan_bad_field",
        module_name="dronecan_bad_field",
        class_name="DroneCANBadField",
        root_namespace="DroneCANBadFieldTypes",
    )

    with pytest.raises(ValueError, match="DSDL field name"):
        generate_module(field_cfg, field_selected)

    namespace_root = tmp_path / "class"
    namespace_root.mkdir()
    (namespace_root / "20001.BadNamespace.uavcan").write_text("uint8 value\n", encoding="utf-8")
    namespace_set = load_dsdl([namespace_root])
    namespace_selected = namespace_set.select_with_dependencies(["class.BadNamespace"])
    namespace_cfg = GenerationConfig(
        output=tmp_path / "dronecan_bad_namespace",
        module_name="dronecan_bad_namespace",
        class_name="DroneCANBadNamespace",
        root_namespace="DroneCANBadNamespaceTypes",
    )

    with pytest.raises(ValueError, match="DSDL namespace component"):
        generate_module(namespace_cfg, namespace_selected)
