"""Exercise the new domain through HA's native config flow with a fake cloud."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from homeassistant import bootstrap, loader
from homeassistant.components.fan import FanEntityFeature
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry

from custom_components.panasonic_smart_cn.const import DOMAIN
from custom_components.panasonic_smart_cn.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.panasonic_smart_cn.exceptions import (
    AirVolumeLockedError,
    CloudError,
)
from custom_components.panasonic_smart_cn.protocol.appliances import (
    BATH_54,
    BATH_RB20,
    PURIFIER_PXP,
    PURIFIER_VXR,
    write_params,
)
from custom_components.panasonic_smart_cn.protocol.erv import ERV_PROTOCOLS
from custom_components.panasonic_smart_cn.protocol.payloads import (
    display_options,
    hardware_validation_pending,
    match_profile,
)

MID = "AABBCCDDEE01_0800_001111"
AIR = "AABBCCDDEE02_0800_001112"
INFO = "AABBCCDDEE03_0800_001113"
UNKNOWN = "AABBCCDDEE04_0900_001114"
BATH = "AABBCCDDEE05_0820_001115"
HEATER = "AABBCCDDEE06_0820_001116"
PURE = "AABBCCDDEE07_0810_001117"
HUMID = "AABBCCDDEE08_0810_001118"
LD6 = "AABBCCDDEE09_0800_001119"
DEVICES = [MID, AIR, INFO, UNKNOWN, BATH, HEATER, PURE, HUMID, LD6]


class Reply:
    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self.data

    def raise_for_status(self):
        pass


class Cloud:
    def __init__(self):
        self.requests = []
        self.mid_status = {"runSta": 1, "runM": 4, "airVo": 2}
        self.ld6_readbacks = []
        self.ld6_status = {"runSta": 1, "runM": 1, "airVo": 1}

    def post(self, url, *, json, headers, ssl, allow_redirects):
        route = url.rsplit("/", 1)[1]
        self.requests.append((route, json, headers))
        if route == "UsrGetToken":
            return Reply({"results": {"token": "example-challenge"}})
        if route == "UsrLogin":
            return Reply({"results": {"usrId": "account", "ssId": "test-session"}})
        if route == "UsrGetBindDevInfo":
            return Reply(
                {
                    "results": {
                        "devList": [
                            self.device(
                                MID,
                                "MIDERV",
                                "客厅",
                                self.mid_status.copy(),
                            ),
                            self.device(
                                AIR,
                                "Aircle-13-03",
                                "书房",
                                {"runSta": 1, "runM": 6, "airVo": 0},
                            ),
                            self.device(INFO, "LD5C", "卧室", {}),
                            self.device(UNKNOWN, "DCERV", "其他设备", {}),
                            self.device(BATH, "Aircle-05-02", "浴霸", {}),
                            self.device(HEATER, "54BA1C", "智暖", {}),
                            self.device(PURE, "63C8PX", "净化器", {}),
                            self.device(HUMID, "113C8VX", "加湿净化器", {}),
                            self.device(LD6, "LD6C", "餐厅", {}, "FV-35ZDP2C"),
                        ]
                    }
                }
            )
        if route == "ADevGetStatusInfoLD5C":
            return Reply(
                {"results": {"runningStatus": 1, "runningMode": 5, "airVolume": 3}}
            )
        if route == "ADevGetStatusMidERV":
            return Reply({"results": {"runSta": 1, "oaPMC": 12}})
        if route == "ADevGetStatusLD6C":
            if self.ld6_readbacks:
                self.ld6_status.update(self.ld6_readbacks.pop(0))
            return Reply({"results": self.ld6_status.copy()})
        if route == "ADevGetStatusInfoFV54BA1C":
            if json["deviceId"] == BATH:
                status = {
                    "runningMode": 38,
                    "lightSet": 0,
                    "timeHourLeft": 0,
                    "timeMinuteLeft": 25,
                    "remAirHighTimeSet": 6,
                }
            else:
                status = {"runningMode": 60}
            return Reply({"results": status})
        if route == "ADevGetStatusInfoPXP60C":
            return Reply(
                {"results": {"runningStatus": 1, "airVolume": 0, "filterTimeLeft": 55}}
            )
        if route == "ADevGetStatusInfoVXR110C":
            return Reply(
                {
                    "results": {
                        "runningStatus": 1,
                        "runningMode": 0,
                        "airVolume": 4,
                        "humidification": 1,
                        "humiCur": 39,
                        "pm25Quti": 20,
                    }
                }
            )
        if route == "ADevSetStatusMidERV":
            self.mid_status["runM"] = json["params"]["runM"]
        if route.startswith("ADevSetStatus"):
            return Reply({"errorCode": 0})
        raise AssertionError(f"Unexpected cloud route: {route}")

    @staticmethod
    def device(device_id, subtype, name, status, model=None):
        return {
            "deviceId": device_id,
            "deviceName": name,
            "params": {
                "devSubTypeId": subtype,
                "statusAll": status,
                "deviceMNO": model,
            },
        }


class PanasonicIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_native_login_multiple_devices_and_entity_values(self):
        cloud = Cloud()
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "custom_components").symlink_to(
                Path.cwd() / "custom_components"
            )
            hass = HomeAssistant(tmp)
            try:
                loader.async_setup(hass)
                await bootstrap.async_from_config_dict({"homeassistant": {}}, hass)
                await hass.async_start()
                with (
                    patch(
                        f"custom_components.{DOMAIN}.config_flow.async_get_clientsession",
                        return_value=cloud,
                    ),
                    patch(
                        f"custom_components.{DOMAIN}.api.client.async_get_clientsession",
                        return_value=cloud,
                    ),
                ):
                    flow = await hass.config_entries.flow.async_init(
                        DOMAIN, context={"source": SOURCE_USER}
                    )
                    self.assertEqual(flow["step_id"], "user")
                    flow = await hass.config_entries.flow.async_configure(
                        flow["flow_id"],
                        {"username": "mock-user", "password": "mock-password"},
                    )
                    self.assertEqual(flow["step_id"], "device")
                    options = next(iter(flow["data_schema"].schema.values())).config[
                        "options"
                    ]
                    self.assertEqual({item["value"] for item in options}, set(DEVICES))
                    self.assertTrue(any("仅状态" in item["label"] for item in options))
                    self.assertEqual(
                        {
                            item["value"]
                            for item in options
                            if "未实机验证" in item["label"]
                        },
                        set(DEVICES) - {UNKNOWN, LD6},
                    )
                    flow = await hass.config_entries.flow.async_configure(
                        flow["flow_id"], {"devices": DEVICES}
                    )
                    self.assertEqual(flow["type"], FlowResultType.CREATE_ENTRY)
                    entry = flow["result"]
                    self.assertEqual(entry.state, ConfigEntryState.LOADED)
                    self.assertEqual(
                        [route for route, _, _ in cloud.requests].count(
                            "UsrGetBindDevInfo"
                        ),
                        2,
                    )
                    registry = entity_registry.async_get(hass)
                    entity_id = registry.async_get_entity_id(
                        "fan", DOMAIN, f"{DOMAIN}_{MID}_fan"
                    )
                    self.assertEqual(
                        hass.states.get(entity_id).attributes["preset_mode"], "自动"
                    )
                    self.assertEqual(
                        hass.states.get(entity_id).attributes["speed_label"], "中"
                    )
                    mode_entity = registry.async_get_entity_id(
                        "select", DOMAIN, f"{DOMAIN}_{MID}_run_mode_select"
                    )
                    self.assertIsNotNone(mode_entity)
                    self.assertTrue(mode_entity.endswith("_operating_mode"))
                    self.assertEqual(hass.states.get(mode_entity).state, "自动")
                    self.assertIn(
                        "睡眠", hass.states.get(mode_entity).attributes["options"]
                    )
                    await hass.services.async_call(
                        "select",
                        "select_option",
                        {"entity_id": mode_entity, "option": "睡眠"},
                        blocking=True,
                    )
                    mid_requests = [
                        body
                        for route, body, _ in cloud.requests
                        if route == "ADevSetStatusMidERV"
                    ]
                    self.assertEqual(mid_requests[-1]["params"]["runM"], 3)
                    speed = registry.async_get_entity_id(
                        "select", DOMAIN, f"{DOMAIN}_{LD6}_air_volume"
                    )
                    ld6_fan = registry.async_get_entity_id(
                        "fan", DOMAIN, f"{DOMAIN}_{LD6}_fan"
                    )
                    controller = entry.runtime_data.devices[LD6]
                    self.assertEqual(
                        hass.states.get(speed).attributes["options"],
                        ["低噪音", "弱", "强"],
                    )
                    self.assertEqual(hass.states.get(speed).state, "弱")
                    with self.assertRaises(AirVolumeLockedError):
                        await controller._set_fields({"runM": 7, "airVo": 1})
                    await controller._set_fields({"runM": 7, "airVo": 2})
                    self.assertEqual(cloud.requests[-1][1]["params"]["airVo"], 255)
                    with self.assertRaises(AirVolumeLockedError):
                        await controller._set_fields({"airVo": 1})
                    cloud.ld6_status.update(runM=7, airVo=2)
                    await entry.runtime_data.async_refresh()
                    self.assertEqual(hass.states.get(speed).state, "强")
                    self.assertEqual(
                        hass.states.get(speed).attributes["options"], ["强"]
                    )
                    features = FanEntityFeature(
                        hass.states.get(ld6_fan).attributes["supported_features"]
                    )
                    self.assertNotIn(FanEntityFeature.SET_SPEED, features)
                    self.assertIn(FanEntityFeature.TURN_OFF, features)
                    writes_before = len(cloud.requests)
                    with self.assertRaises(AirVolumeLockedError):
                        await controller._set_fields({"airVo": 1})
                    self.assertEqual(len(cloud.requests), writes_before)
                    await controller._set_fields({"runM": 4})
                    cloud.ld6_status["runM"] = 4
                    await entry.runtime_data.async_refresh()
                    self.assertEqual(
                        hass.states.get(speed).attributes["options"],
                        ["低噪音", "弱", "强"],
                    )
                    self.assertIn(
                        FanEntityFeature.SET_SPEED,
                        FanEntityFeature(
                            hass.states.get(ld6_fan).attributes["supported_features"]
                        ),
                    )
                    await controller._set_fields({"airVo": 1})
                    self.assertEqual(cloud.requests[-1][1]["params"]["airVo"], 1)
                    ld6_mode = registry.async_get_entity_id(
                        "select", DOMAIN, f"{DOMAIN}_{LD6}_run_mode_select"
                    )
                    with patch(
                        "custom_components.panasonic_smart_cn.api.client.CONTROL_READBACK_DELAYS",
                        (0, 0, 0),
                    ):
                        # Mode arrives first. Strong airflow is part of confirmation.
                        cloud.ld6_readbacks = [
                            {"runM": 4, "airVo": 1},
                            {"runM": 7},
                            {"airVo": 2},
                        ]
                        start = len(cloud.requests)
                        await hass.services.async_call(
                            "select",
                            "select_option",
                            {"entity_id": ld6_mode, "option": "消毒"},
                            blocking=True,
                        )
                        self.assertEqual(
                            [route for route, _, _ in cloud.requests[start:]],
                            ["ADevSetStatusLD6C", *["ADevGetStatusLD6C"] * 3],
                        )
                        self.assertEqual(hass.states.get(ld6_mode).state, "消毒")
                        self.assertEqual(hass.states.get(speed).state, "强")
                        self.assertEqual(hass.states.get(mode_entity).state, "睡眠")

                        start = len(cloud.requests)
                        with self.assertRaises(HomeAssistantError) as caught:
                            await hass.services.async_call(
                                "select",
                                "select_option",
                                {"entity_id": ld6_mode, "option": "内循环"},
                                blocking=True,
                            )
                        self.assertEqual(
                            caught.exception.translation_key, "control_not_confirmed"
                        )
                        self.assertEqual(
                            [route for route, _, _ in cloud.requests[start:]],
                            ["ADevSetStatusLD6C", *["ADevGetStatusLD6C"] * 3],
                        )
                        self.assertEqual(hass.states.get(ld6_mode).state, "消毒")

                    self.assertIsNone(
                        registry.async_get_entity_id(
                            "fan", DOMAIN, f"{DOMAIN}_{UNKNOWN}_fan"
                        )
                    )
                    diagnostic = registry.async_get_entity_id(
                        "sensor", DOMAIN, f"{DOMAIN}_{UNKNOWN}_protocol"
                    )
                    self.assertEqual(hass.states.get(diagnostic).state, "仅状态")
                    entry.runtime_data.data[MID]["token"] = "test-raw-token"
                    report = await async_get_config_entry_diagnostics(hass, entry)
                    self.assertTrue(report["polling_ok"])
                    self.assertEqual(len(report["devices"]), len(DEVICES))
                    self.assertEqual(
                        {
                            (item["protocol"], item["hardware_validation_pending"])
                            for item in report["devices"]
                        }
                        & {
                            ("MIDERV", True),
                            ("54BA1C", True),
                            ("LD6C", False),
                            (None, False),
                        },
                        {
                            ("MIDERV", True),
                            ("54BA1C", True),
                            ("LD6C", False),
                            (None, False),
                        },
                    )
                    for secret in (
                        "mock-password",
                        "mock-user",
                        MID,
                        "test-session",
                        "test-raw-token",
                    ):
                        self.assertNotIn(secret, repr(report))

                    bath_mode = registry.async_get_entity_id(
                        "select", DOMAIN, f"{DOMAIN}_{BATH}_bath_mode"
                    )
                    heater_mode = registry.async_get_entity_id(
                        "select", DOMAIN, f"{DOMAIN}_{HEATER}_bath_mode"
                    )
                    bath_light = registry.async_get_entity_id(
                        "light", DOMAIN, f"{DOMAIN}_{BATH}_light"
                    )
                    pure = registry.async_get_entity_id(
                        "fan", DOMAIN, f"{DOMAIN}_{PURE}_purifier"
                    )
                    humid = registry.async_get_entity_id(
                        "fan", DOMAIN, f"{DOMAIN}_{HUMID}_purifier"
                    )
                    self.assertEqual(hass.states.get(bath_mode).state, "换气")
                    self.assertEqual(hass.states.get(heater_mode).state, "24小时换气")
                    self.assertEqual(hass.states.get(bath_light).state, "off")
                    self.assertEqual(
                        hass.states.get(pure).attributes["preset_mode"], "自动"
                    )
                    self.assertEqual(
                        hass.states.get(humid).attributes["speed_label"], "急速"
                    )

                    await entry.runtime_data.devices[BATH]._set_fields(
                        {"runningMode": 38}
                    )
                    route, body, headers = cloud.requests[-1]
                    self.assertEqual(route, "ADevSetStatusInfoFV54BA1C")
                    self.assertEqual(body["id"], 52)
                    self.assertEqual(body["params"]["timeSet"], 6)
                    self.assertEqual(body["params"]["lightSet"], 255)
                    self.assertIn("/0820/RB20VL1/", headers["Referer"])

                    await entry.runtime_data.devices[HUMID]._set_fields(
                        {"airVolume": 4, "runningMode": 0}
                    )
                    route, body, _ = cloud.requests[-1]
                    self.assertEqual(route, "ADevSetStatusInfoVXR110C")
                    self.assertEqual(body["params"]["airVolume"], 4)
                    self.assertEqual(body["params"]["humidification"], 255)

                    client = entry.runtime_data.devices[INFO]
                    await client._set_fields({"runM": 5})
                    route, body, headers = cloud.requests[-1]
                    self.assertEqual(route, "ADevSetStatusInfoLD5C")
                    self.assertEqual(body["deviceId"], INFO)
                    self.assertEqual(body["params"]["runningMode"], 5)
                    self.assertEqual(headers["xtoken"], "SSID=test-session")

                    await entry.runtime_data.devices[AIR]._set_fields({"runM": 6})
                    route, body, _ = cloud.requests[-1]
                    self.assertEqual(route, "ADevSetStatusDCERV")
                    self.assertEqual(body["params"]["runM"], 6)
                    self.assertEqual(body["params"]["tH1"], 127)

                    flow = await hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
                        data=entry.data,
                    )
                    self.assertEqual(flow["step_id"], "reauth_confirm")
                    flow = await hass.config_entries.flow.async_configure(
                        flow["flow_id"], {"password": "replacement"}
                    )
                    self.assertEqual(flow["reason"], "reauth_successful")
                    self.assertEqual(entry.data["password"], "replacement")
                    await hass.async_block_till_done()

                    flow = await hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={
                            "source": SOURCE_RECONFIGURE,
                            "entry_id": entry.entry_id,
                        },
                    )
                    self.assertEqual(flow["step_id"], "device")
                    flow = await hass.config_entries.flow.async_configure(
                        flow["flow_id"], {"devices": [MID, AIR, INFO]}
                    )
                    self.assertEqual(flow["reason"], "reconfigure_successful")
                    await hass.async_block_till_done()
                    self.assertIsNone(hass.states.get(diagnostic))
                    self.assertEqual(
                        hass.states.get(entity_id).attributes["preset_mode"], "睡眠"
                    )
            finally:
                await hass.async_stop()

    def test_model_matching_does_not_guess_an_unknown_variant(self):
        self.assertEqual(match_profile(MID, "SMALLERV-02", None), "SMALLERV02")
        self.assertIsNone(match_profile(MID, None, "FY-25ZDP1C"))
        for subtype, model in (
            ("LD6C", "FV-50ZDP2C"),
            ("LD6C", "FV-25ZDP2C"),
            ("NEWDCERV", "FV-RZ09VD2"),
            ("SMALLERV02", "FY-25ZM1C"),
            ("MIDERV", "FV-RZ06VD1"),
            ("DCERV-03", "FY-35ZJD2C"),
            ("LD6C", "FY-70ZR1C"),
        ):
            with self.subTest(model=model):
                self.assertIsNone(match_profile(MID, subtype, model))
        self.assertEqual(match_profile(MID, "LD6C", "FV-35ZDP2C"), "LD6C")
        self.assertEqual(match_profile(MID, "DCERV-03", None), "DCERV")
        self.assertIsNone(match_profile(MID, "DCERV-99", None))
        self.assertIsNone(match_profile(MID, "LD5C-Y", "FY-25ZDP1C"))
        self.assertIsNone(match_profile(UNKNOWN, "DCERV", None))
        self.assertEqual(match_profile(BATH, "Aircle-05-02", None), BATH_RB20)
        self.assertEqual(match_profile(HEATER, None, "FV-54BA1C"), BATH_54)
        self.assertEqual(match_profile(PURE, None, "F-PXP60C"), PURIFIER_PXP)
        self.assertEqual(match_profile(PURE, None, "F-63C8PX"), PURIFIER_PXP)
        self.assertEqual(match_profile(HUMID, None, "F-VXR110C"), PURIFIER_VXR)
        self.assertEqual(match_profile(HUMID, None, "F-113C8VX"), PURIFIER_VXR)
        self.assertIsNone(match_profile(BATH, "Aircle-05-02", "FV-40BQ1C"))
        self.assertIsNone(match_profile(PURE, "RB20VL1", None))
        self.assertIsNone(match_profile(BATH, "54BA1C", "FV-RB20VL1"))
        self.assertIsNone(match_profile(PURE, "PXP60C", "unknown-model"))

    def test_ld6c_hardware_evidence_is_model_specific(self):
        for model in ("FV-25ZDP2C", "FV-50ZDP2C", None):
            with self.subTest(model=model):
                self.assertTrue(hardware_validation_pending("LD6C", model))
        self.assertFalse(hardware_validation_pending("LD6C", "FV-35ZDP2C"))
        self.assertTrue(hardware_validation_pending("AIRCLE-13-03", "FV-35ZDP2C"))

    def test_commands_reject_unsupported_fields_and_values(self):
        with self.assertRaises(CloudError):
            write_params(BATH_RB20, {"runningMode": 44}, {})
        with self.assertRaises(CloudError):
            write_params(PURIFIER_PXP, {"airVolume": 4}, {})
        with self.assertRaises(CloudError):
            write_params(BATH_54, {"gasCheckSet": 1}, {})

    def test_apk_erv_model_matching_and_info_packets(self):
        self.assertEqual(match_profile(MID, None, "FV-09ZVDH1C"), "ERV")
        self.assertEqual(match_profile(MID, None, "FY-35ZDP1CX"), "LD5C-X")
        self.assertEqual(match_profile(MID, None, "FY-70ZR1C"), "CABINET")
        self.assertTrue(ERV_PROTOCOLS["LD5C-X"].read_url.endswith("GetStatusInfoLD5CX"))
        self.assertTrue(ERV_PROTOCOLS["LD5C-X"].write_url.endswith("SetStatusInfoLD5C"))
        self.assertEqual(display_options("LD5C-X")[1]["严寒"], 5)
        self.assertEqual(
            ERV_PROTOCOLS["ERV"].normalize(
                {"runningStatus": 1, "runningMode": 4, "airVolume": 2}
            ),
            {"runSta": 1, "runM": 4, "airVo": 2},
        )
        identity = {"deviceId": "device", "token": "token", "usrId": "user"}
        ld5c = ERV_PROTOCOLS["LD5C"]
        self.assertEqual(ld5c.read_body(identity), {"id": 2, **identity})
        self.assertEqual(
            ld5c.write_body(99, identity, {"runningMode": 5}),
            {"id": 0, **identity, "params": {"runningMode": 5}},
        )
        self.assertIsNone(ld5c.decode_status({"holidayMode": 1}))
        self.assertEqual(
            ld5c.decode_status({"runSta": 0, "runningStatus": 1}), {"runSta": 1}
        )
        cabinet = ERV_PROTOCOLS["CABINET"].payload_builder(
            "device", "token", "user", airVo=5
        )
        self.assertEqual(cabinet["airVolume"], 5)
        self.assertEqual(cabinet["PM25AutoSensitivity"], 255)
        self.assertNotIn("autoSensitivity", cabinet)

    def test_app_labels_and_wire_codes_are_independent(self):
        cases = {
            "DCERV": ("热交换", 48, {0: "弱", 1: "强"}),
            "MIDERV": ("自动", 4, {1: "弱", 2: "中", 3: "强"}),
            "NEWDCERV": ("睡眠", 3, {1: "弱", 2: "中", 3: "强"}),
            "LD5C": ("外循环", 5, {1: "弱", 2: "中", 3: "强"}),
            "LD6C": ("消毒", 7, {0: "低噪音", 1: "弱", 2: "强"}),
            "SMALLERV": (None, None, {0: "低", 1: "高"}),
            "SMALLERV02": (None, None, {1: "低", 3: "高"}),
            "AIRCLE-13-03": ("热交换", 1, {0: "低噪音", 1: "弱", 2: "强"}),
        }
        for profile, (label, wire_value, speeds) in cases.items():
            with self.subTest(profile=profile):
                reads, writes, actual_speeds = display_options(profile)
                self.assertEqual(writes.get(label), wire_value)
                self.assertEqual(reads.get(wire_value), label)
                self.assertEqual(actual_speeds, speeds)
