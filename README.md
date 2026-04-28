# xrobot-dronecan-dsdlc

DroneCAN DSDL compiler for XRobot and LibXR projects.

The compiler reads DroneCAN/UAVCAN v0 `.uavcan` DSDL definitions and emits an
XRobot module repository layout:

- `module.yaml`
- root header-only `{module_name}.hpp`
- `CMakeLists.txt`
- generated C++ DSDL codecs and an `Application` wrapper in the root header

The generated C++ module depends on the existing `dronecan_core` module for the
LibXR CAN bridge and libcanard runtime.

## Usage

Generate a module for ESC RawCommand and Status from the bundled DroneCAN specs:

```powershell
python -m pip install -e .
xr_dronecan_dsdlc generate `
  --builtin-dsdl `
  --type uavcan.equipment.esc.RawCommand `
  --type uavcan.equipment.esc.Status `
  --module-name dronecan_esc_generated `
  --class-name DroneCANEscGenerated `
  --output D:\Codes\Modules\dronecan_esc_generated
```

The generated module can be referenced from XRobot configuration like:

```yaml
modules:
  - id: dronecan_esc_generated
    name: dronecan_esc_generated
    constructor_args:
      node_id: 10
      can_alias: can0
      timebase_alias: timebase
      node_name: org.libxr.dronecan.generated
      node_status_period_ms: 1000
```

## Notes

- DSDL parsing and data type signature computation are delegated to the official
  `dronecan` Python package, so generated constants match DroneCAN v0.
- Generated codecs use `canardEncodeScalar()` and `canardDecodeScalar()` from
  the `dronecan_core` module's libcanard copy.
- Dynamic tail arrays use DroneCAN tail-array optimization by default.
