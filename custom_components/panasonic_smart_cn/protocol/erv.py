"""ERV protocol definitions and codecs adapted from rudyll (MIT)."""

from collections.abc import Callable
from dataclasses import dataclass, field

from ..const import BASE_URL
from . import mappings

# GET/SET 三端均用 48-53（2026-04-22 实测确认）
RUN_MODE_GET_MAP: dict[int, str] = {
    48: "热交换",
    49: "静音",
    50: "普通换气",
    51: "内循环",
    52: "混风",
    53: "自动ECO",
    # 旧固件 / 初始状态可能返回 0-5（与 48-53 一一对应）
    0: "热交换",
    1: "静音",
    2: "普通换气",
    3: "内循环",
    4: "混风",
    5: "自动ECO",
}

RUN_MODE_SET_MAP: dict[str, int] = {
    "热交换": 48,
    "静音": 49,
    "普通换气": 50,
    "内循环": 51,
    "混风": 52,
    "自动ECO": 53,
}

AIR_VOLUME_MAP: dict[int, str] = {
    0: "弱",
    1: "强",
}

# MidERV 与 NewDCERV 共享运行模式值域。NewDCERV 睡眠时会自动降至弱风。
MID_MODES = {0: "热交换", 2: "内循环", 3: "睡眠", 4: "自动"}
MID_MODE_WRITES = {label: code for code, label in MID_MODES.items()}

# FV-RZ09VD2 的 NewDCERV 端点里室外温湿度是占位值，真实读数要从 MidERV 端点补。
NEWDCERV_AUX_SENSOR_KEYS: tuple[str, ...] = ("oaHumC", "oaTeC")

# LD6C（FV-25/35/50ZDP2C）映射来自松下 App 的 Ld6cBeanConvert。
LD6C_RUN_MODE_GET_MAP: dict[int, str] = {
    1: "热交换",
    4: "内循环",
    6: "自动ECO",
    7: "消毒",
}

LD6C_RUN_MODE_SET_MAP: dict[str, int] = {
    label: value for value, label in LD6C_RUN_MODE_GET_MAP.items()
}

LD6C_AIR_VOLUME_MAP: dict[int, str] = {0: "低噪音", 1: "弱", 2: "强"}

# LD5C（FY-25ZDP1C）协议来自松下官方 Web 控制页
# https://app.psmartcloud.com/ca/cn/0800/LD5C/index.html 的 js/common/api_utility.js，
# 由 dkong5ssss 定位并经 FY-25ZDP1C 用户实机验证（本仓库 issue #11）。
# 该页无证书固定，JS 源码即官方协议：Info 家族端点 + 长驼峰字段名。
LD5C_RUN_MODE_GET_MAP: dict[int, str] = {
    0: "热交换",
    2: "内循环",
    5: "外循环",
}

LD5C_RUN_MODE_SET_MAP: dict[str, int] = {
    label: value for value, label in LD5C_RUN_MODE_GET_MAP.items()
}

# Info GET 返回的长驼峰字段 → 实体代码使用的内部短字段名。
LD5C_STATUS_FIELD_MAP: dict[str, str] = {
    "runningStatus": "runSta",
    "runningMode": "runM",
    "airVolume": "airVo",
    "holidayMode": "holM",
    "oaPM25Cur": "oaPMC",
    "saPM25Cur": "saPMC",
    "raPM25Cur": "raPMC",
    "oaTempCur": "oaTeC",
    "saTempCur": "saTeC",
    "raTempCur": "raTeC",
    "oaHumidityCur": "oaHumC",
    "saHumidityCur": "saHumC",
    "raHumidityCur": "raHumC",
}

# 内部短字段名 → LD5C SET payload 的长驼峰字段名。
LD5C_SET_FIELD_MAP: dict[str, str] = {
    "runSta": "runningStatus",
    "runM": "runningMode",
    "airVo": "airVolume",
    "holM": "holidayMode",
}

# Info GET 的传感器字段在本机型全部返回占位值，真实读数只能从 MidERV 端点取。
LD5C_AUX_SENSOR_KEYS: tuple[str, ...] = ("oaPMC", "oaHumC", "oaTeC", "raFilExTL")

# SmallERV 风量来自 App 的 MiniErvBeanConvert。
SMALLERV_AIR_VOLUME_MAP: dict[int, str] = {0: "低", 1: "高"}
# FY-25ZM1C（devSubTypeId=SMALLERV02）实机报告使用独立值域：1=低、3=高。
SMALLERV02_AIR_VOLUME_MAP: dict[int, str] = {1: "低", 3: "高"}

# FY-25ZM1C 的字段前缀与 App 展示名称并非一一对应，名称按实机截图校准。
SMALLERV02_FILTER_FIELD_LABELS: dict[str, str] = {
    "filClTL": "滤网清洁倒计时",
    "oaFilClFirTL": "回风侧滤网更换倒计时",
    "oaFilExPMTL": "PM2.5滤网更换倒计时",
    "reFilExTL": "初效滤网更换倒计时",
}

# 占位值必须按字段判断，不能全局过滤：例如 PM2.5 的 255 可能是真实读数，
# 而温度的 127、湿度的 255、PM2.5/CO₂ 的 65535 是协议无效值。
SENSOR_INVALID_VALUES: dict[str, frozenset[int]] = {
    "oaPMC": frozenset({65535}),
    "saPMC": frozenset({65535}),
    "raPMC": frozenset({65535}),
    "oaHumC": frozenset({255}),
    "saHumC": frozenset({255}),
    "raHumC": frozenset({255}),
    "oaTeC": frozenset({127, 255}),
    "saTeC": frozenset({127, 255}),
    "raTeC": frozenset({127, 255}),
    "raCO2C": frozenset({65535}),
    "raTVC": frozenset({255}),
    "oaFilExTL": frozenset({65535}),
    "saFilExTL": frozenset({65535}),
    "raFilExTL": frozenset({65535}),
    "resFilExTL": frozenset({65535}),
    "filClTL": frozenset({65535}),
    "oaFilClFirTL": frozenset({65535}),
    "oaFilExPMTL": frozenset({65535}),
    "reFilExTL": frozenset({65535}),
    "pmFstFilClTL": frozenset({65535}),
    "pmFstFilExTL": frozenset({65535}),
    "returnInFilExTL": frozenset({65535}),
}


def is_invalid_sensor_value(key: str, value) -> bool:
    """Return whether value is a protocol sentinel for this sensor field."""
    try:
        numeric = int(value)
    except TypeError, ValueError:
        return False
    return numeric in SENSOR_INVALID_VALUES.get(key, ())


def build_dcerv_payload(device_id: str, token: str, usr_id: str, **overrides) -> dict:
    """构造 DCERV-03 完整 SET payload（来自 App 源码 DevStatusSetBean）。

    所有字段默认 255（skip），tH/tMin 默认 127，overrides 覆盖需要改的字段。
    """
    p: dict = {
        "deviceId": device_id,
        "token": token,
        "usrId": usr_id,
        "runSta": 255,
        "runM": 255,
        "airVo": 255,
        "preSet": 255,
        "preM": 255,
        "holM": 255,
        "pmSen": 255,
        "coSen": 255,
        "tvSen": 255,
        "userSupWind": 255,
        "userExhWind": 255,
        "aircJoi": 255,
        "oaFilEx": 255,
    }
    for i in range(1, 7):
        p[f"tSta{i}"] = 255
        p[f"tM{i}"] = 255
        p[f"tWind{i}"] = 255
        p[f"tSet{i}"] = 255
        p[f"tH{i}"] = 127
        p[f"tMin{i}"] = 127
        p[f"tWeek{i}"] = 255
    p.update(overrides)
    return p


def build_miderv_payload(device_id: str, token: str, usr_id: str, **overrides) -> dict:
    """构造 MidERV 完整 SET payload（字段来自参考仓库 SAFE_CONTROL_KEYS）。"""
    p: dict = {
        "deviceId": device_id,
        "token": token,
        "usrId": usr_id,
        "runSta": 255,
        "runM": 255,
        "airVo": 255,
        "preM": 255,
        "autoSen": 255,
        "coldF": 255,
        "saSet": 255,
        "HeatM": 255,
        "holM": 255,
        "oaFilCl": 255,
        "raFilCl": 255,
        "raFilEx": 255,
        "saFilCl": 255,
        "oaFilEx": 255,
        "saFilEx": 255,
        # MidERV 定时器：on/off 各一组，不是 DCERV 的 1-6 循环
        "tOnH": 127,
        "tOnMin": 127,
        "tOnSta": 255,
        "tOffH": 127,
        "tOffMin": 127,
        "tOffSta": 255,
    }
    p.update(overrides)
    return p


def build_smallerv_payload(
    device_id: str, token: str, usr_id: str, **overrides
) -> dict:
    """构造 App `MiniErvDevStatusSetBean` 对应的完整 SET payload。"""
    p: dict = {
        "deviceId": device_id,
        "token": token,
        "usrId": usr_id,
        "runSta": 255,
        "airVo": 255,
        # App Bean 唯一不是 skip 值的默认字段。
        "filSet": 0,
        "oaFilExPM": 255,
        "saFilEx": 255,
        "holM": 255,
    }
    for i in range(1, 7):
        # MiniErvDevStatusSetBean 将小时和分钟也覆盖为 255。
        for prefix in ("tSta", "tSet", "tH", "tMin", "tWeek"):
            p[f"{prefix}{i}"] = 255
    p.update(overrides)
    return p


def build_newdcerv_payload(
    device_id: str, token: str, usr_id: str, **overrides
) -> dict:
    """构造 App `NewDevSetBean` 对应的完整 SET payload。"""
    fields = (
        "runSta",
        "runM",
        "airVo",
        "preM",
        "holM",
        "autoSen",
        "nanoe",
        "oaPMC",
        "pmFstFilCl",
        "pmFstFilEx",
        "oaFilEx",
        "returnInFilEx",
        "InLoopFilEx",
    )
    p: dict = {
        "deviceId": device_id,
        "token": token,
        "usrId": usr_id,
        **{field: 255 for field in fields},
    }
    for i in range(1, 7):
        p[f"tSta{i}"] = 255
        p[f"tSet{i}"] = 255
        p[f"tH{i}"] = 127
        p[f"tMin{i}"] = 127
        p[f"tWeek{i}"] = 255
    p.update(overrides)
    return p


def build_ld6c_payload(device_id: str, token: str, usr_id: str, **overrides) -> dict:
    """构造 App `Ld6cDevStateSetBean` 对应的完整 SET payload。"""
    fields = (
        "runSta",
        "runM",
        "airVo",
        "winDir",
        "heatM",
        "nanoe",
        "preSet",
        "preM",
        "holM",
        "pmSen",
        "co2Sen",
        "tvSen",
        "saFilCl",
        "oaFilCl",
        "resFilCl",
        "saFilEX",
        "oaFilEx",
        "resFilEx",
        "saFilSet",
        "tSet",
        "slfSendW",
        "slfOutW",
        "airBind",
        "clFilReset",
        "saFilExReset",
        "oaFilExReset",
        "raFilExReset",
        "resFilExReset",
        "dehumid",
        "humidSet",
        "breathLight",
    )
    p: dict = {
        "deviceId": device_id,
        "token": token,
        "usrId": usr_id,
        **{field: 255 for field in fields},
    }
    for i in range(1, 7):
        for prefix in ("tSta", "tM", "tWind", "tSet", "tH", "tMin", "tWeek"):
            p[f"{prefix}{i}"] = 255
    for i in range(1, 11):
        p[f"res{i}"] = 255
    p.update(overrides)
    return p


def build_ld5c_payload(device_id: str, token: str, usr_id: str, **overrides) -> dict:
    """构造官方 Web 控制页 `ADevSetStatusInfoLD5C` 的完整 SET payload。

    与其他机型不同，Info 家族端点把 usrId/deviceId/token 放在请求体顶层而不是
    params 里，所以这里只返回控制字段；身份字段由 `build_set_body` 补上。
    overrides 用内部短字段名（runSta/runM/airVo/holM），这里翻译成官方长字段名。
    """
    fields = (
        "runningStatus",
        "runningMode",
        "airVolume",
        "heatingMode",
        "pPressureMode",
        "holidayMode",
        "autoSensitivity",
        "oaFilterExist",
        "saFilterClCycle",
        "oaFilterClCycle",
        "saFilterExCycle",
        "oaFilterExCycle",
        "saFilterExist",
        "onTimerSetting",
        "offTimerSetting",
    )
    p: dict = {field: 255 for field in fields}
    # 定时器的时/分用 127 表示保持不变。
    for key in ("onTimerHour", "onTimerMinute", "offTimerHour", "offTimerMinute"):
        p[key] = 127
    for key, value in overrides.items():
        p[LD5C_SET_FIELD_MAP.get(key, key)] = value
    return p


def build_cabinet_payload(device_id: str, token: str, usr_id: str, **overrides) -> dict:
    params = build_ld5c_payload(device_id, token, usr_id, **overrides)
    del params["autoSensitivity"]
    params.update(
        dict.fromkeys(
            (
                "nanoe",
                "airDirection",
                "PM25AutoSensitivity",
                "CO2AutoSensitivity",
                "panelLockSetting",
            ),
            255,
        )
    )
    return params


def build_legacy_aircle_payload(
    device_id: str, token: str, user_id: str, **overrides
) -> dict:
    """Build a DCERV set payload with skip sentinels for unchanged fields."""
    payload: dict = {
        "deviceId": device_id,
        "token": token,
        "usrId": user_id,
        "runSta": 255,
        "runM": 255,
        "airVo": 255,
        "preSet": 255,
        "preM": 255,
        "holM": 255,
        "pmSen": 255,
        "coSen": 255,
        "tvSen": 255,
        "userSupWind": 255,
        "userExhWind": 255,
        "aircJoi": 255,
        "oaFilEx": 255,
    }
    for index in range(1, 7):
        payload[f"tSta{index}"] = 255
        payload[f"tM{index}"] = 255
        payload[f"tWind{index}"] = 255
        payload[f"tSet{index}"] = 255
        payload[f"tH{index}"] = 127
        payload[f"tMin{index}"] = 127
        payload[f"tWeek{index}"] = 255
    payload.update(overrides)
    return payload


@dataclass(frozen=True)
class ErvProtocol:
    """One ERV family's matching, transport, state and control capabilities."""

    endpoint: str
    payload_builder: Callable[..., dict]
    speeds: dict[int, str]
    modes: dict[int, str] = field(default_factory=dict)
    mode_writes: dict[str, int] = field(default_factory=dict)
    models: tuple[str, ...] = ()
    set_endpoint: str | None = None
    live_status: bool = False
    info_format: bool = False
    read_id: int = 3
    write_id: int | None = None
    referer: str | None = None
    sensor_keys: tuple[str, ...] | None = None
    auxiliary_keys: tuple[str, ...] = ()
    carry_status_keys: tuple[str, ...] = ()
    auxiliary_controls: tuple[str, ...] = ()
    action_fields: tuple[str, ...] = ()
    fixed_speeds: dict[int, int] = field(default_factory=dict)
    experimental: bool = False

    @property
    def read_url(self) -> str:
        return f"{BASE_URL}/ADevGetStatus{self.endpoint}"

    @property
    def write_url(self) -> str:
        return f"{BASE_URL}/ADevSetStatus{self.set_endpoint or self.endpoint}"

    @property
    def writable_fields(self) -> frozenset[str]:
        fields = {"runSta", "airVo", *self.auxiliary_controls, *self.action_fields}
        if self.mode_writes:
            fields.add("runM")
        return frozenset(fields)

    def normalize(self, results: dict) -> dict:
        if not self.info_format:
            return results
        normalized = {
            key: value
            for key, value in results.items()
            if key not in LD5C_STATUS_FIELD_MAP
        }
        normalized.update(
            {
                short: results[long]
                for long, short in LD5C_STATUS_FIELD_MAP.items()
                if long in results
            }
        )
        return normalized

    def decode_status(self, results) -> dict | None:
        if not isinstance(results, dict):
            return None
        status = self.normalize(results)
        return status if "runSta" in status or "airVo" in status else None

    def read_body(self, identity: dict) -> dict:
        if self.info_format:
            return {"id": self.read_id, **identity}
        return {"id": self.read_id, "uiVersion": 4.0, "params": identity}

    def write_body(self, request_id: int, identity: dict, params: dict) -> dict:
        body = {
            "id": request_id if self.write_id is None else self.write_id,
            "params": params,
        }
        if self.info_format:
            body.update(identity)
        return body


LEGACY_AIRCLE = "AIRCLE-13-03"
THREE_SPEEDS = {1: "弱", 2: "中", 3: "强"}

ERV_PROTOCOLS = {
    "DCERV": ErvProtocol(
        "DCERV",
        build_dcerv_payload,
        AIR_VOLUME_MAP,
        modes=RUN_MODE_GET_MAP,
        mode_writes=RUN_MODE_SET_MAP,
        live_status=True,
        sensor_keys=(
            "oaPMC",
            "saPMC",
            "raPMC",
            "oaHumC",
            "raHumC",
            "oaTeC",
            "saTeC",
            "raTeC",
            "raCO2C",
            "raTVC",
            "oaFilExTL",
            "saFilExTL",
            "raFilExTL",
        ),
    ),
    "NEWDCERV": ErvProtocol(
        "NewDCERV",
        build_newdcerv_payload,
        THREE_SPEEDS,
        modes=MID_MODES,
        mode_writes=MID_MODE_WRITES,
        live_status=True,
        sensor_keys=(
            "oaPMC",
            "oaHumC",
            "oaTeC",
            "pmFstFilClTL",
            "pmFstFilExTL",
            "returnInFilExTL",
        ),
        auxiliary_keys=NEWDCERV_AUX_SENSOR_KEYS,
        carry_status_keys=("oaPMC",),
        auxiliary_controls=("nanoe",),
    ),
    "MIDERV": ErvProtocol(
        "MidERV",
        build_miderv_payload,
        THREE_SPEEDS,
        modes=MID_MODES,
        mode_writes=MID_MODE_WRITES,
    ),
    "LD6C": ErvProtocol(
        "LD6C",
        build_ld6c_payload,
        LD6C_AIR_VOLUME_MAP,
        modes=LD6C_RUN_MODE_GET_MAP,
        mode_writes=LD6C_RUN_MODE_SET_MAP,
        models=("FV-35ZDP2C",),
        live_status=True,
        sensor_keys=(
            "oaPMC",
            "raPMC",
            "oaHumC",
            "oaTeC",
            "oaFilExTL",
            "saFilExTL",
            "raFilExTL",
            "resFilExTL",
        ),
        fixed_speeds={7: 2},
    ),
    "LD5C": ErvProtocol(
        "InfoLD5C",
        build_ld5c_payload,
        THREE_SPEEDS,
        modes=LD5C_RUN_MODE_GET_MAP,
        mode_writes=LD5C_RUN_MODE_SET_MAP,
        live_status=True,
        info_format=True,
        read_id=2,
        write_id=0,
        sensor_keys=LD5C_AUX_SENSOR_KEYS,
        auxiliary_keys=LD5C_AUX_SENSOR_KEYS,
    ),
    "SMALLERV": ErvProtocol(
        "SmallERV", build_smallerv_payload, SMALLERV_AIR_VOLUME_MAP
    ),
    "SMALLERV02": ErvProtocol(
        "SmallERV",
        build_smallerv_payload,
        SMALLERV02_AIR_VOLUME_MAP,
        live_status=True,
        sensor_keys=(
            "oaPMC",
            "oaHumC",
            "oaTeC",
            "filClTL",
            "oaFilClFirTL",
            "oaFilExPMTL",
            "reFilExTL",
        ),
    ),
    LEGACY_AIRCLE: ErvProtocol(
        "DCERV",
        build_legacy_aircle_payload,
        mappings.AIR_VOLUME_MAP,
        modes=mappings.RUN_MODE_READ_MAP,
        mode_writes=mappings.RUN_MODE_SET_MAP,
        auxiliary_controls=("holM", "breathLight", "preSet", "pmSen", "slfOutW"),
        action_fields=(
            "clFilReset",
            "resFilExReset",
            "oaFilExReset",
            "saFilExReset",
            "raFilExReset",
        ),
        fixed_speeds={7: 2},
    ),
    # These mappings come from APK 4.101.0 and the official Info endpoints.
    "ERV": ErvProtocol(
        "InfoERV",
        build_ld5c_payload,
        THREE_SPEEDS,
        modes=MID_MODES,
        mode_writes=MID_MODE_WRITES,
        models=("FV-09ZVDH1C", "FV-RZ09VD1"),
        live_status=True,
        info_format=True,
        referer="0800/ERV",
        experimental=True,
    ),
    "LD5C-X": ErvProtocol(
        "InfoLD5CX",
        build_ld5c_payload,
        THREE_SPEEDS,
        modes={0: "热交换", 2: "内循环", 5: "严寒"},
        mode_writes={"热交换": 0, "内循环": 2, "严寒": 5},
        models=("FY-15ZDP1CX", "FY-25ZDP1CX", "FY-35ZDP1CX"),
        set_endpoint="InfoLD5C",
        live_status=True,
        info_format=True,
        referer="0800/LD5C-X",
        experimental=True,
    ),
    "CABINET": ErvProtocol(
        "InfoFloorPlacedERV",
        build_cabinet_payload,
        {value: f"风量{value}" for value in range(1, 6)},
        modes={0: "热交换", 2: "内循环", 6: "静音", 4: "自动"},
        mode_writes={"热交换": 0, "内循环": 2, "静音": 6, "自动": 4},
        models=("FY-50ZR1C", "FY-70ZR1C"),
        live_status=True,
        info_format=True,
        referer="0800/CABINET",
        experimental=True,
    ),
}
