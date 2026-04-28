from pathlib import Path

from xrobot_dronecan_dsdlc.dsdl import load_dsdl
from xrobot_dronecan_dsdlc.generator import GenerationConfig, generate_module


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
    assert (out / "module.yaml").exists()
    assert (out / "CMakeLists.txt").exists()
    assert (out / "dronecan_esc_generated.hpp").exists()
    assert sorted(path.name for path in out.glob("*.hpp")) == ["dronecan_esc_generated.hpp"]
    assert not list(out.rglob("*.cpp"))
    assert not (out / "DroneCANEscGenerated.hpp").exists()
    assert not (out / "include" / "dronecan_esc_generated" / "dronecan_esc_generated_types.hpp").exists()
    generated_hpp = out / "include" / "dronecan_esc_generated" / "dronecan_esc_generated_generated.hpp"
    assert generated_hpp.exists()

    module_yaml = (out / "module.yaml").read_text(encoding="utf-8")
    assert "name: dronecan_esc_generated" in module_yaml
    assert "class_name: DroneCANEscGenerated" in module_yaml
    assert "header: dronecan_esc_generated.hpp" in module_yaml

    cmake = (out / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "target_include_directories(xr PUBLIC" in cmake
    assert "${CMAKE_CURRENT_LIST_DIR}" in cmake
    assert "${CMAKE_CURRENT_LIST_DIR}/include" in cmake
    assert "target_sources" not in cmake
    assert ".cpp" not in cmake

    module_hpp = (out / "dronecan_esc_generated.hpp").read_text(encoding="utf-8")
    assert "/* === MODULE MANIFEST V2 ===" in module_hpp
    assert "constructor_args:" in module_hpp
    assert "node_id: 10" in module_hpp
    assert "can_alias: can0" in module_hpp
    assert "depends:" in module_hpp
    assert "- dronecan_core" in module_hpp
    assert "=== END MANIFEST === */" in module_hpp
    assert '#include "dronecan_esc_generated/dronecan_esc_generated_generated.hpp"' in module_hpp
    assert "using dronecan_esc_generated = DroneCANEscGenerated;" in module_hpp
    assert "inline DroneCANEscGenerated::DroneCANEscGenerated(" not in module_hpp
    assert "kDataTypeId = 1030U" not in module_hpp

    generated = generated_hpp.read_text(encoding="utf-8")
    assert "inline DroneCANEscGenerated::DroneCANEscGenerated(" in generated
    assert "inline void DroneCANEscGenerated::OnMonitor()" in generated
    assert "kDataTypeId = 1030U" in generated
    assert "0x217F5C87D7EC951DULL" in generated
    assert "std::array<std::int16_t, 20U> cmd" in generated
