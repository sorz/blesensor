#!/usr/bin/python3

"""Copyright (c) 2019, Douglas Otwell
Copyright (c) 2020, Shell Chen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import time
import dbus
import json
import struct
import platform
from pathlib import Path
from typing import Optional, Dict, List

from advertisement import Advertisement
from service import Application, Service, Characteristic, Descriptor
from gpiozero import CPUTemperature

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
MEASUREMENT_STALED_SECS = 5000
NOTIFY_TIMEOUT = 3000

class SensorAdvertisement(Advertisement):
    def __init__(self, index):
        super().__init__(index, "peripheral")
        self.add_local_name(platform.node())
        self.include_tx_power = True

class SensorService(Service):
    SENSOR_SVC_UUID = "00000001-710e-4a5b-8d75-3e5b444bc3cf"
    MEASUREMENT_JSON = Path('/dev/shm/sensor.json')
    SENSOR_KEY_NAME = (
        ('eCO2', 'eCO2 (ppm)'),
        ('eCH2O', 'eCH2O (ppm)'),
        ('TVOC', 'TVOC (ppm)'),
        ('PM25', 'PM 2.5 (ug/m^3)'),
        ('PM10', 'PM 10 (ug/m^3)'),
        ('Temp', 'Temperature (celsius)'),
        ('Humi', 'Relative humidity (%)')
    )

    def __init__(self, index):
        super().__init__(index, self.SENSOR_SVC_UUID, True)
        for uuid, (key, name) in enumerate(self.SENSOR_KEY_NAME):
            self.add_characteristic(MeasurementCharacteristic(self, uuid, key, name))

    def read_measurement(self) -> Optional[Dict[str, int]]:
        if not self.MEASUREMENT_JSON.is_file():
            return
        with open(self.MEASUREMENT_JSON) as f:
            m = json.load(f)
        if time.time() - m.pop('time') > MEASUREMENT_STALED_SECS:
            return
        return m

class MeasurementCharacteristic(Characteristic):
    CHARACTERISTIC_UUID = "0000%04x-710e-4a5b-8d75-3e5b444bc3cf"

    def __init__(self, service: SensorService, uuid: int, key: str, desc: str):
        self.notifying = False
        super().__init__(
                self.CHARACTERISTIC_UUID % uuid,
                ["notify", "read"], service)
        self.key = key
        self.add_descriptor(MeasurementDescriptor(self, desc))

    def read_measurement(self) -> Optional[List[dbus.Byte]]:
        m = self.service.read_measurement()
        print(self.key, m)
        if m is None or self.key not in m:
            return
        return [dbus.Byte(b) for b in struct.pack('!i', m[self.key])]

    def set_measurement_callback(self):
        if self.notifying:
            value = self.read_measurement()
            self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": value}, [])
        return self.notifying

    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        value = self.read_measurement()
        if value is not None:
            self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": value}, [])
        self.add_timeout(NOTIFY_TIMEOUT, self.set_measurement_callback)

    def StopNotify(self):
        self.notifying = False

    def ReadValue(self, options):
        return self.read_measurement() or []

class MeasurementDescriptor(Descriptor):
    DESCRIPTOR_UUID = "2901"

    def __init__(self, characteristic: MeasurementCharacteristic, name: str):
        super().__init__(
                self.DESCRIPTOR_UUID,
                ["read"],
                characteristic)
        self.name = name

    def ReadValue(self, options):
        return [dbus.Byte(c.encode()) for c in self.name]

app = Application()
app.add_service(SensorService(0))
app.register()

adv = SensorAdvertisement(0)
adv.register()

try:
    app.run()
except KeyboardInterrupt:
    app.quit()
