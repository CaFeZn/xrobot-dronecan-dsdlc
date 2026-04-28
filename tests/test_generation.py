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
    assert (out / "DroneCANEscGenerated.hpp").exists()
    assert (out / "src" / "DroneCANEscGenerated.cpp").exists()
    assert (out / "include" / "dronecan_esc_generated" / "dronecan_esc_generated_types.hpp").exists()

    module_yaml = (out / "module.yaml").read_text(encoding="utf-8")
    assert "name: dronecan_esc_generated" in module_yaml
    assert "class_name: DroneCANEscGenerated" in module_yaml

    types_hpp = (out / "include" / "dronecan_esc_generated" / "dronecan_esc_generated_types.hpp").read_text(
        encoding="utf-8"
    )
    assert "kDataTypeId = 1030U" in types_hpp
    assert "0x217F5C87D7EC951DULL" in types_hpp
    assert "std::array<std::int16_t, 20U> cmd" in types_hpp
