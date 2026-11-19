# Panasonic Smart CN

`custom_components/panasonic_smart_cn` 是独立的 Home Assistant 自定义集成，使用自己的配置条目、设备和实体。每个松下账号共用一个会话和一个数据协调器。集成在 HA Core 中运行，经松下云读取账号下已绑定设备的状态并控制支持的设备。

## 使用

将 `custom_components/panasonic_smart_cn` 目录放到 Home Assistant 的 `/config/custom_components/` 下并重启 Core。在「设置 → 设备与服务 → 添加集成」搜索 **Panasonic Smart CN**，输入中国区「松下智能家电」账号，选择要添加的设备。之后可通过集成的「重新配置」更新设备列表。松下会话失效时，Home Assistant 会提示重新认证。自动重新登录默认关闭，因为松下的会话策略可能影响手机 App。

## 协议与显示

按云端设备类别、子类型及已知销售型号匹配。已实现 DCERV、NewDCERV、MidERV、LD5C、LD6C、SmallERV、SmallERV02，以及 `Aircle-13-03` 兼容路径。原生风机实体提供开关、百分比风量和运行模式。支持模式切换的新风机同时在设备页提供独立的「运行模式」下拉框，中文风量档位在「风量」下拉框选择。空气质量和滤网实体按协议提供。

### 控制结果

控制开关、风量或模式后，集成会回读状态。若 Home Assistant 提示「松下云已接收指令，但在等待时间内未读到与指令一致的状态」，后续常规刷新仍会更新实际状态。旧协议可能只提供云端状态快照，滤网复位等一次性动作只能确认云端接收。

### LD6C 风量

风量文案采用松下 App 的「低噪音／弱／强」，对应 `airVo=0/1/2`。消毒模式 `runM=7` 由设备使用强风量。HA 在消毒时只显示「强」，禁用风量滑杆，拒绝其他风量写入。退出消毒并回读普通模式后恢复三个档位。切换运行模式和整机开关仍可用。


### 0.1 适配机型

以下配置以 APK 4.101.0 的 `air_dev_feature.json`、`air_dev_yuba.json`、`air_dev_filter.json` 和 `air_dev_supply.json` 为型号与档位依据。松下控制页用于核对实际接口、请求结构以及保留值。**下表机型均标注为「未实机验证」**，配置列表和设备的「设备协议」诊断实体均有标注。

| 品类或子类型 | 可匹配销售型号 | HA 中的日常功能 |
| --- | --- | --- |
| 浴霸 `RB20VL1` | FV-RB20VL1，也匹配云端子类型 `Aircle-05-02` | 待机、取暖、换气、凉干燥、热干燥、照明、有限时的剩余运行时间 |
| 浴霸 `54BA1C` | FV-54BA1C | 取暖、强弱换气、凉／热干燥、24 小时换气、除菌、待机和剩余运行时间 |
| 净化器 `PXP60C` | F-PXP60C、F-63C8PX | 开关、自动、三档风量、滤网剩余百分比 |
| 加湿净化器 `VXR110C` | F-VXR110C、F-113C8VX | 开关、风量、预设模式、加湿开关、滤网剩余、PM2.5 与室内湿度 |
| 壁挂新风 `ERV` | FV-09ZVDH1C、FV-RZ09VD1 | 开关、热交换、内循环、睡眠、自动与三档风量 |
| 薄型新风 `LD5C-X` | FY-15ZDP1CX、FY-25ZDP1CX、FY-35ZDP1CX | 开关、热交换、内循环、严寒与三档风量 |
| 柜式新风 `CABINET` | FY-50ZR1C、FY-70ZR1C | 开关、热交换、内循环、静音、自动与五档风量 |

RB20VL1 的控制页只开放一组换气及干燥模式，本版本按该控制页提供选项。VXR110C 的「急速」使用控制页确认的 `airVolume=4`。LD5C-X 读取走 `ADevGetStatusInfoLD5CX`，写入走 `ADevSetStatusInfoLD5C`，与普通 LD5C 的读取路径不同。

独立排风扇、其余浴霸以及其他家电暂时只显示为「仅状态」。需确认具体型号与云端读写映射，才能开放控制。浴霸的换气模式已在表中列出。

- [松下 RB20VL1 控制脚本](https://app.psmartcloud.com/ca/cn/0820/RB20VL1/js/common/api_utility.js) · [松下 54BA1C 控制脚本](https://app.psmartcloud.com/ca/cn/0820/54BA1C/js/common/api_utility.js)
- [松下 PXP60C 控制脚本](https://app.psmartcloud.com/ca/cn/0810/PXP60C/js/common/api_utility.js) · [松下 VXR110C 档位脚本](https://app.psmartcloud.com/ca/cn/0810/VXR110C/js/common/common_contents.js)
- [松下 ERV 控制脚本](https://app.psmartcloud.com/ca/cn/0800/ERV/js/common/api_utility.js) · [松下 LD5C-X 控制脚本](https://app.psmartcloud.com/ca/cn/0800/LD5C-X/js/common/api_utility.js) · [松下 CABINET 控制脚本](https://app.psmartcloud.com/ca/cn/0800/CABINET/js/common/api_utility.js)

显示名称与协议值分别维护。例如 DCERV 的「热交换」使用 `48`，LD6C 的「热交换」使用 `1`。LD5C 的「外循环」使用实机协议值 `5`。APK 资源里的部分界面枚举与实际请求值域不同。开发时参照了 APK 4.101.0 的资源、松下 Web 控制资源和 MIT 授权的社区实现。来源许可随组件附带。

本项目已确认的实机组合为 FV-35ZDP2C（LD6C）。其他适配型号标注为「未实机验证」。LD6C 当前开放整机开关、模式和风量控制。
