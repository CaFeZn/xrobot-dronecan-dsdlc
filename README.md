# xrobot-dronecan-dsdlc

面向 XRobot 和 LibXR 项目的 DroneCAN DSDL 编译器。

DroneCAN DSDL compiler for XRobot and LibXR projects.

编译器读取 DroneCAN/UAVCAN v0 `.uavcan` DSDL 定义，并生成 XRobot 模块仓库布局：

The compiler reads DroneCAN/UAVCAN v0 `.uavcan` DSDL definitions and emits an
XRobot module repository layout:

- `module.yaml`
- 根级单文件 `{module_name}.hpp` / root single-file `{module_name}.hpp`
- `CMakeLists.txt`
- 同一个根头文件内的 C++ DSDL 编解码器和 `Application` 包装类 / C++ DSDL codecs and an `Application` wrapper in the same root header

生成的 C++ 模块依赖现有 `dronecan_core` 模块提供 LibXR CAN 桥接和 libcanard 运行时。

The generated C++ module depends on the existing `dronecan_core` module for the
LibXR CAN bridge and libcanard runtime.

## 用法 / Usage

从内置 DroneCAN 规范生成 ESC RawCommand 和 Status 模块：

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

生成的模块可以在 XRobot 配置中这样引用：

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

## 说明 / Notes

- DSDL 解析和数据类型签名计算由官方 `dronecan` Python 包完成，因此生成常量与 DroneCAN v0 保持一致。
- DSDL parsing and data type signature computation are delegated to the official
  `dronecan` Python package, so generated constants match DroneCAN v0.
- 生成的编解码器使用 `dronecan_core` 模块内 libcanard 提供的 `canardEncodeScalar()` 和 `canardDecodeScalar()`。
- Generated codecs use `canardEncodeScalar()` and `canardDecodeScalar()` from
  the `dronecan_core` module's libcanard copy.
- 动态尾数组默认使用 DroneCAN tail-array optimization。
- Dynamic tail arrays use DroneCAN tail-array optimization by default.
