# xrobot-dronecan-dsdlc

面向 XRobot 和 LibXR 项目的 DroneCAN DSDL 编译器。

DroneCAN DSDL compiler for XRobot and LibXR projects.

编译器读取 DroneCAN/UAVCAN v0 `.uavcan` DSDL 定义，并生成 XRobot 模块仓库布局：

The compiler reads DroneCAN/UAVCAN v0 `.uavcan` DSDL definitions and emits an
XRobot module repository layout:

- 根级 `{module_name}.hpp` 稳定 XRobot 入口和 `MODULE MANIFEST V2` / root `{module_name}.hpp` stable XRobot entry and `MODULE MANIFEST V2`
- `generated/{module_name}.hpp` 生成的 XRobot facade / generated XRobot facade
- `generated/{module_name}_dsdl_detail.hpp` 公共编解码 helper / shared codec helpers
- `generated/{type_name}.hpp` 每个 DSDL 类型一个生成头 / one generated header per emitted DSDL type
- `.gitignore`，默认忽略 `generated/` / `.gitignore`, ignoring `generated/` by default
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

不传 `--type`、且没有从 `--xrobot-yaml` 读取 `generator.dsdl.types` 时，生成器只输出
`uavcan.protocol.NodeStatus`，也就是基础节点健康状态报文。其它 LED、动态 ID 或项目自定义
DSDL 类型应在用户工程配置里显式传入。

When `--type` is omitted and `generator.dsdl.types` is not read from
`--xrobot-yaml`, only `uavcan.protocol.NodeStatus` is emitted for the base node
health report. LED, dynamic-ID, or project-specific DSDL types should be
requested explicitly by the consuming project.

推荐在用户工程 `User/xrobot.yaml` 的模块项里保存生成配置：

Prefer storing generation inputs in the module entry of the consuming project's
`User/xrobot.yaml`:

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
    generator:
      dsdl:
        builtin: true
        types:
          - uavcan.equipment.indication.LightsCommand
          - uavcan.protocol.dynamic_node_id.Allocation
        class_name: DroneCANDsdl
        root_namespace: DroneCANGeneratedDsdl
        core_module_id: CaFeZn/dronecan_core
```

然后从 YAML 生成：

Then generate from YAML:

```powershell
xr_dronecan_dsdlc generate `
  --xrobot-yaml User/xrobot.yaml `
  --module-id dronecan_dsdl
```

也可以用独立生成配置文件，适合 CI、脚本或暂时不想把生成字段放进
`User/xrobot.yaml` 的项目：

Alternatively, use a standalone generation config. This is useful for CI,
scripts, or projects that do not want generation keys inside `User/xrobot.yaml`:

```yaml
# User/dronecan.yaml
dronecan:
  module:
    name: dronecan_dsdl
    class_name: DroneCANDsdl
    root_namespace: DroneCANGeneratedDsdl
    output: Modules/dronecan_dsdl
    core_module_id: CaFeZn/dronecan_core

  node:
    default_node_id: 10
    node_name: org.libxr.dronecan.generated
    node_status_period_ms: 1000
    can_alias: can0
    timebase_alias: timebase

  dsdl:
    builtin: true
    source_dirs: []
    lookup_dirs: []
    types:
      - uavcan.equipment.indication.LightsCommand
      - uavcan.protocol.dynamic_node_id.Allocation
```

```powershell
xr_dronecan_dsdlc generate --config User/dronecan.yaml
```

命令行参数会覆盖 YAML 中的同类配置。例如同时传入 `--config` 和 `--type`
时，输出类型列表以命令行 `--type` 为准。`--config` 和 `--xrobot-yaml` 互斥。

Command-line options override matching YAML values. For example, when both
`--config` and `--type` are provided, the emitted type list comes from `--type`.
`--config` and `--xrobot-yaml` are mutually exclusive.

## 生成模式 / Generation Modes

默认模式是 `facade-own-node`：生成类继承 `LibXR::Application`，自己从
`HardwareContainer` 查找 CAN/Timebase，持有 `DroneCANNode`，并在
`OnMonitor()` 中轮询。这适合简单 demo 或单一 DroneCAN facade。

The default mode is `facade-own-node`: the generated class derives from
`LibXR::Application`, looks up CAN/Timebase from `HardwareContainer`, owns a
`DroneCANNode`, and polls it from `OnMonitor()`. This fits simple demos or a
single DroneCAN facade.

`binding-only` 模式只接收外部 `DroneCANCoreSupport::DroneCANNode&`，不持有
CAN、Timebase、arena 或 DroneCANNode，也不注册 Application。它适合多个 generated
binding 共享同一个 `dronecan_core` 运行时。

`binding-only` accepts an external `DroneCANCoreSupport::DroneCANNode&` only. It
does not own CAN, Timebase, an arena, or a DroneCANNode, and it does not register
an Application. Use it when multiple generated bindings should share one
`dronecan_core` runtime.

```yaml
dronecan:
  module:
    name: dronecan_dsdl
    class_name: DroneCANDsdl
    root_namespace: DroneCANGeneratedDsdl
    output: Modules/dronecan_dsdl
    mode: binding-only
  dsdl:
    builtin: true
    messages:
      - name: uavcan.equipment.esc.RawCommand
        rx: true
        tx: false
        callback: true
        topic: false
      - name: uavcan.equipment.esc.Status
        rx: false
        tx: true
        callback: false
        topic: false
    services:
      - name: uavcan.protocol.GetNodeInfo
        server: true
        client: false
        callback: true
```

XRobot 工程中可以把共享 runtime 和 binding-only DSDL facade 分开实例化：

In an XRobot project, instantiate the shared runtime and binding-only DSDL
facade separately:

```yaml
modules:
  - id: dronecan_core
    name: DroneCANCoreModule
    constructor_args:
      node_id: 10
      can_alias: can1
      timebase_alias: timebase
      node_name: org.libxr.dronecan
      node_status_period_ms: 1000

  - id: dronecan_dsdl
    name: dronecan_dsdl
    constructor_args:
      node: "@dronecan_core"
    generator:
      dsdl:
        mode: binding-only
        builtin: true
        messages:
          - name: uavcan.equipment.esc.RawCommand
            rx: true
            tx: false
            callback: true
            topic: false
          - name: uavcan.equipment.esc.Status
            rx: false
            tx: true
            callback: false
            topic: false
```

## API 裁剪 / API Pruning

旧的 `types:` 列表仍然可用，并保持兼容：每个 message 默认生成 RX handler、
callback setter 和 publish 方法；每个 service 默认生成 request/response 两侧 API。

The legacy `types:` list remains supported and compatible: each message emits
RX handlers, callback setters, and publish methods; each service emits both
request/response sides.

需要节省 ROM/RAM 或避免注册无用 handler 时，用 `messages:` / `services:` 精确声明：

Use `messages:` / `services:` when ROM/RAM should be reduced or unused handlers
should not be registered:

- command 类 message 通常 `rx: true, tx: false, callback: true`。
- status/event 类 message 通常 `rx: false, tx: true`。
- 需要在 LibXR 内部转发的 message 可启用 `topic: true`；RX topic 名称为
  `/dronecan/<type>`，TX topic 名称为 `/dronecan/tx/<type>`。
- service server 端通常 `server: true, client: false, callback: true`。
- service client 端通常 `server: false, client: true, callback: true`。

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

XRobot 模块元数据写在根级 `{module_name}.hpp` 的 `MODULE MANIFEST V2` 中；
生成器不再输出 `module.yaml`。DSDL 类型 header 名称由生成器按类型名默认推导。
所有项目相关生成产物都放在 `generated/` 子目录，模块仓库默认通过 `.gitignore`
忽略该目录。

XRobot module metadata is stored in `MODULE MANIFEST V2` inside the root
`{module_name}.hpp`; the generator no longer emits `module.yaml`. Type header
names are derived from DSDL type names. Project-specific generated artifacts
live under `generated/`, which is ignored by the generated module `.gitignore`.

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
