# xrobot-dronecan-dsdlc

面向 XRobot 和 LibXR 项目的 DroneCAN DSDL 编译器。

DroneCAN DSDL compiler for XRobot and LibXR projects.

编译器读取 DroneCAN/UAVCAN v0 `.uavcan` DSDL 定义，并生成 XRobot 模块仓库布局：

The compiler reads DroneCAN/UAVCAN v0 `.uavcan` DSDL definitions and emits an
XRobot module repository layout:

- `module.yaml`
- 根级 `{module_name}.hpp` 稳定 XRobot 入口 / root `{module_name}.hpp` stable XRobot entry
- `generated/{module_name}.hpp` 生成的 XRobot facade / generated XRobot facade
- `generated/{module_name}_dsdl_detail.hpp` 公共编解码 helper / shared codec helpers
- `generated/{type_name}.hpp` 每个 DSDL 类型一个生成头 / one generated header per emitted DSDL type
- `CMakeLists.txt`
- C++ DSDL 编解码器拆分到独立类型头文件，`Application` 包装类保留在 facade 头文件内 / C++ DSDL codecs split into per-type headers, with the `Application` wrapper kept in the facade header

生成的 C++ 模块依赖现有 `dronecan_core` 模块提供 LibXR CAN 桥接和 libcanard 运行时。

The generated C++ module depends on the existing `dronecan_core` module for the
LibXR CAN bridge and libcanard runtime.

## 用法 / Usage

从内置 DroneCAN 规范生成 ESC RawCommand、Status 和 DynamicNodeId Allocation 模块：

Generate a module for ESC RawCommand, Status, and DynamicNodeId Allocation from
the bundled DroneCAN specs:

推荐把输出目录指向独立的 XRobot 模块仓库，例如 `dronecan_dsdl` 的本地克隆；消费工程再通过 `modules.yaml` / `sources.yaml` 同步该仓库。

Prefer writing the output to a standalone XRobot module repository, such as a
local clone of `dronecan_dsdl`; consuming projects should then synchronize that
repository through `modules.yaml` / `sources.yaml`.

```powershell
python -m pip install -e .
xr_dronecan_dsdlc generate `
  --builtin-dsdl `
  --type uavcan.equipment.esc.RawCommand `
  --type uavcan.equipment.esc.Status `
  --type uavcan.protocol.dynamic_node_id.Allocation `
  --module-name dronecan_dsdl `
  --class-name DroneCANDsdl `
  --root-namespace DroneCANGeneratedDsdl `
  --core-module-id CaFeZn/dronecan_core `
  --output D:\Codes\DroneCAN\dronecan_dsdl
```

生成的 `module.yaml` 中，`dsdl` 列表只记录 DSDL 类型名；
header 文件名由生成器按类型名默认推导。所有生成产物都放在 `generated/` 子目录，
模块根目录只保留稳定入口和配置。

In the generated `module.yaml`, the `dsdl` list records only DSDL type names.
Header file names are derived by the generator from type names. All generated
artifacts live under `generated/`; the module root keeps only the stable entry
and configuration.

```yaml
dsdl:
- type: uavcan.equipment.esc.RawCommand
- type: uavcan.equipment.esc.Status
- type: uavcan.protocol.dynamic_node_id.Allocation
```

默认生成的类型 header 名称示例：

Default generated type header names:

```text
generated/uavcan_equipment_esc_raw_command.hpp
generated/uavcan_equipment_esc_status.hpp
generated/uavcan_protocol_dynamic_node_id_allocation.hpp
```

在 `User/xrobot.yaml` 中实例化生成的 facade；`dronecan_core` 作为依赖由构建系统加入，不需要在这里单独实例化。

Instantiate the generated facade in `User/xrobot.yaml`. `dronecan_core` is added
as a dependency by the build and does not need a separate entry here.

如果该模块通过 `xrobot_init_mod` 作为独立模块仓库同步，manifest 中的
`depends` 必须使用完整模块 ID。默认依赖是 `CaFeZn/dronecan_core`，可用
`--core-module-id` 改成你的私有 namespace。

When this module is synchronized as a standalone module repository through
`xrobot_init_mod`, the manifest `depends` entry must use a full module ID. The
default dependency is `CaFeZn/dronecan_core`; use `--core-module-id` for a
private namespace.

```yaml
modules:
  - id: dronecan_dsdl
    name: dronecan_dsdl
    constructor_args:
      node_id: 10
      can_alias: can0
      timebase_alias: timebase
      node_name: org.libxr.dronecan.generated
      node_status_period_ms: 1000
```

## 自定义 DSDL / Custom DSDL

自定义 DSDL 时，把 DSDL 根命名空间目录作为位置参数传给 `generate`，并用
`--type` 指定完整类型名。保留 `--builtin-dsdl` 可以继续解析标准 `uavcan.*`
依赖。

For custom DSDL, pass the DSDL root namespace directory as a positional
argument and specify full type names with `--type`. Keep `--builtin-dsdl` if
your custom types reference standard `uavcan.*` dependencies.

目录示例 / Directory example:

```text
CustomDSDL/
  my_company/
    actuator/
      20000.MyCommand.uavcan
```

生成示例 / Generation example:

```powershell
xr_dronecan_dsdlc generate `
  D:\Path\To\CustomDSDL\my_company `
  --builtin-dsdl `
  --type my_company.actuator.MyCommand `
  --module-name dronecan_custom `
  --class-name DroneCANCustom `
  --root-namespace DroneCANCustomDsdl `
  --core-module-id CaFeZn/dronecan_core `
  --output D:\Codes\DroneCAN\dronecan_custom
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
