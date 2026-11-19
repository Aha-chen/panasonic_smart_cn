"""Model-specific contracts from Panasonic's public CN control pages."""

from dataclasses import dataclass, field

from ..const import BASE_URL
from ..exceptions import CloudError
from .device_id import ParsedDeviceId

BATH_RB20 = "RB20VL1"
BATH_54 = "54BA1C"
PURIFIER_PXP = "PXP60C"
PURIFIER_VXR = "VXR110C"

BATH_TIMER_KEYS = {
    37: "remWarmTimeSet",
    38: "remAirHighTimeSet",
    39: "remAirLowTimeSet",
    40: "remCoolHighTimeSet",
    41: "remCoolLowTimeSet",
    42: "remHotHighTimeSet",
    43: "remHotLowTimeSet",
}
BATH_DEFAULTS = dict.fromkeys(
    (
        "runningMode",
        "warmTempset",
        "windDirectionSet",
        "windKindSet",
        "timeSet",
        "DIYnextRunningMode",
        "DIYnextWarmTempset",
        "DIYnextwindDirectionSet",
        "DIYnextwindKindSet",
        "DIYnextTimeSet",
    ),
    255,
)
PURIFIER_DEFAULTS = dict.fromkeys(("runningStatus", "airVolume", "nanoe", "led"), 255)


@dataclass(frozen=True)
class ApplianceProtocol:
    endpoint_suffix: str
    status_key: str
    web_path: str
    aliases: tuple[str, ...]
    writable_values: dict[str, set[int]]
    write_defaults: dict[str, int]
    bath_modes: dict[int, str] = field(default_factory=dict)
    allow_empty_write: bool = False
    status_id: int = 100
    write_id: int = 200

    @property
    def category(self) -> str:
        return self.web_path.split("/", 1)[0]

    @property
    def read_url(self) -> str:
        return f"{BASE_URL}/ADevGetStatusInfo{self.endpoint_suffix}"

    @property
    def write_url(self) -> str:
        return f"{BASE_URL}/ADevSetStatusInfo{self.endpoint_suffix}"

    def decode_status(self, results) -> dict | None:
        if isinstance(results, dict) and self.status_key in results:
            return results
        return None


_RB20_MODES = {32: "待机", 37: "取暖", 38: "换气", 40: "凉干燥", 42: "热干燥"}
_54_MODES = {
    32: "待机",
    37: "取暖",
    38: "换气（强）",
    39: "换气（弱）",
    40: "凉干燥（强）",
    41: "凉干燥（弱）",
    42: "热干燥（强）",
    43: "热干燥（弱）",
    44: "24小时换气",
    45: "除菌",
}

APPLIANCE_PROTOCOLS = {
    BATH_RB20: ApplianceProtocol(
        "FV54BA1C",
        "runningMode",
        "0820/RB20VL1",
        ("FV-RB20VL1", BATH_RB20, "AIRCLE-05-02"),
        {"runningMode": set(_RB20_MODES), "lightSet": {0, 1}},
        {**BATH_DEFAULTS, "lightSet": 255, "DIYnextStepNo": 2},
        bath_modes=_RB20_MODES,
        allow_empty_write=True,
        write_id=52,
    ),
    BATH_54: ApplianceProtocol(
        "FV54BA1C",
        "runningMode",
        "0820/54BA1C",
        ("FV-54BA1C", BATH_54),
        {"runningMode": set(_54_MODES)},
        {**BATH_DEFAULTS, "gasCheckSet": 255, "DIYnextStepNo": 5},
        bath_modes=_54_MODES,
    ),
    PURIFIER_PXP: ApplianceProtocol(
        "PXP60C",
        "runningStatus",
        "0810/PXP60C",
        ("F-PXP60C", PURIFIER_PXP, "F-63C8PX", "63C8PX"),
        {"runningStatus": {0, 1}, "airVolume": {0, 1, 2, 3}},
        {**PURIFIER_DEFAULTS, "sensorSensitivity": 255},
    ),
    PURIFIER_VXR: ApplianceProtocol(
        "VXR110C",
        "runningStatus",
        "0810/VXR110C",
        ("F-VXR110C", PURIFIER_VXR, "F-113C8VX", "113C8VX"),
        {
            "runningStatus": {0, 1},
            "airVolume": {1, 2, 3, 4},
            "runningMode": {0, 1, 11, 12},
            "humidification": {0, 1},
        },
        {
            **PURIFIER_DEFAULTS,
            **dict.fromkeys(
                (
                    "runningMode",
                    "childLock",
                    "dustSensorSensitivity",
                    "gasSensorSensitivity",
                    "humidification",
                ),
                255,
            ),
        },
    ),
}
BATH_MODES = {
    name: protocol.bath_modes
    for name, protocol in APPLIANCE_PROTOCOLS.items()
    if protocol.bath_modes
}
MODEL_ALIASES = {
    (protocol.category, alias): name
    for name, protocol in APPLIANCE_PROTOCOLS.items()
    for alias in protocol.aliases
}


def match_appliance(
    device: ParsedDeviceId, subtype: str | None, model: str | None
) -> str | None:
    """Require a matching category and a supported model or cloud subtype."""
    subtype = (subtype or "").strip().upper()
    model = (model or "").strip().upper()
    subtype_profile = MODEL_ALIASES.get((device.category, subtype))
    if model:
        model_profile = MODEL_ALIASES.get((device.category, model))
        if subtype and subtype_profile != model_profile:
            return None
        return model_profile
    return subtype_profile


def bath_mode(profile: str, raw: int | None) -> str | None:
    if raw in (0, 32, 48):
        return "待机"
    if profile == BATH_54 and raw is not None:
        if 53 <= raw <= 61:
            raw -= 16
        elif 21 <= raw <= 29:
            raw += 16
    return BATH_MODES[profile].get(raw)


def write_params(profile: str, fields: dict[str, int], status: dict) -> dict:
    """Encode only controls backed by the specific model's control contract."""
    if not fields:
        raise CloudError("未指定松下设备控制字段")
    protocol = APPLIANCE_PROTOCOLS[profile]
    if any(
        value not in protocol.writable_values.get(key, ())
        for key, value in fields.items()
    ):
        raise CloudError("该型号尚未支持请求中的控制值")
    params = {**protocol.write_defaults, **fields}
    if not protocol.bath_modes:
        return params
    mode = fields.get("runningMode")
    remembered = status.get(BATH_TIMER_KEYS.get(mode))
    if isinstance(remembered, int) and (
        1 <= remembered <= 34 or (remembered == 35 and mode in {38, 39, 40, 41})
    ):
        params["timeSet"] = remembered
    elif mode == 37:
        # A 15-minute fallback where no remembered heating duration is available.
        params["timeSet"] = 3
    return params
