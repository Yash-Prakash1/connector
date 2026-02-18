"""Tier 3: Rigol DS1054Z oscilloscope module."""

from __future__ import annotations

from hardware_agent.devices.base import DeviceDataSchema, DeviceHints
from hardware_agent.devices.rigol_common import RIGOL_VENDOR_ID, get_rigol_common_hints
from hardware_agent.devices.visa_device import VisaDevice


class RigolDS1054ZModule(VisaDevice):
    VENDOR_ID = RIGOL_VENDOR_ID  # "1AB1"
    PRODUCT_ID = "04CE"
    MODEL_PATTERNS = ["DS1054Z", "DS1074Z", "DS1104Z", "DS1202Z"]
    DEVICE_IDENTIFIER = "rigol_ds1054z"
    DEVICE_NAME = "Rigol DS1054Z"
    MANUFACTURER = "Rigol"
    CATEGORY = "oscilloscope"

    def _get_vendor_hints(self, os: str) -> DeviceHints:
        return get_rigol_common_hints(os)

    def _get_device_specific_quirks(self) -> list[str]:
        return [
            "USB 3.0 ports may cause timeout issues — try USB 2.0",
            "Binary waveform data has TMC header that must be stripped",
            "VXI-11 (LAN) is slower than USB TMC",
        ]

    def generate_example_code(self) -> str:
        return '''\
import pyvisa
import re

rm = pyvisa.ResourceManager('@py')
resources = rm.list_resources()
print("Available VISA resources:", resources)

# Find Rigol DS1054Z (vendor ID 1AB1, product ID 04CE)
matched = [r for r in resources if re.search(r"1AB1", r, re.IGNORECASE)]
if not matched:
    raise RuntimeError("Rigol DS1054Z not found. Check USB connection.")

scope = rm.open_resource(matched[0])
print("Connected to:", scope.query("*IDN?").strip())

# Configure channel 1
scope.write(":CHANnel1:DISPlay ON")
scope.write(":CHANnel1:SCALe 1.0")      # 1V/div
scope.write(":TIMebase:SCALe 0.001")     # 1ms/div

# Take a measurement
vpp = scope.query(":MEASure:ITEM? VPP,CHANnel1").strip()
freq = scope.query(":MEASure:ITEM? FREQ,CHANnel1").strip()
print(f"Vpp: {vpp}")
print(f"Frequency: {freq}")

scope.close()
'''

    def get_data_schema(self) -> DeviceDataSchema:
        return DeviceDataSchema(fields={
            "firmware_version": "str",
            "serial_number": "str",
            "channels_available": "int",
        })
