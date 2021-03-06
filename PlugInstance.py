import random
import logging
from DataSource import DataSource
from typing import Type
from time import time


# Generator for random MAC address
# Thanks to @pklaus: https://gist.github.com/pklaus/9638536
def random_bytes(num=6):
    return [random.randrange(256) for _ in range(num)]


def generate_mac(uaa=False, multicast=False, oui=None, separator=':', byte_fmt='%02x'):
    mac = random_bytes()
    if oui:
        if type(oui) == str:
            oui = [int(chunk, 16) for chunk in oui.split(separator)]
        mac = oui + random_bytes(num=6 - len(oui))
    else:
        if multicast:
            mac[0] |= 1  # set bit 0
        else:
            mac[0] &= ~1  # clear bit 0
        if uaa:
            mac[0] &= ~(1 << 1)  # clear bit 1
        else:
            mac[0] |= 1 << 1  # set bit 1
    return separator.join(byte_fmt % b for b in mac)


def generate_deviceid():
    deviceid_bytes = random_bytes(num=20)
    return ''.join('%02x' % b for b in deviceid_bytes)


class PlugInstance:
    start_time = None
    data_source = None

    def __init__(self, identifier, alias=None, mac=None, device_id=None):
        self.identifier = identifier
        if mac is None:
            gen_mac = generate_mac(oui='53:75:31')
            logging.info("Spoofed MAC: %s", gen_mac)
            self.mac = gen_mac
        else:
            self.mac = mac

        if device_id is None:
            gen_device_id = generate_deviceid()
            logging.info("Spoofed Device ID: %s", gen_device_id)
            self.device_id = gen_device_id
        else:
            self.device_id = device_id

        if alias is None:
            self.alias = "Spoofed TP-Link Kasa HS110 " + self.device_id[0:8]
        else:
            self.alias = alias

    @classmethod
    # Convenience method to create a lot of plugs
    def configure_plugs(cls, plugs, data_source_class: Type[DataSource], data_controller=None):
        # Loop through all plugs
        instances = []
        for plug in plugs:
            # Get specified identifier
            plug_id = next(iter(plug.keys()))
            # Get plug details
            details = plug.get(plug_id)
            if details is not None:
                # Define main details
                alias = details.get('alias')
                mac = details.get('mac')
                device_id = details.get('device_id')

                # Create and configure instance
                instance = cls(plug_id, alias, mac, device_id)

                # Generate data source with details, and assign
                instance.data_source = data_source_class(plug_id, details, data_controller)
                instances.append(instance)

                logging.debug(f"Added plug: {plug_id}")

        return instances

    @property
    def power(self):
        return self.data_source.get_power()

    def generate_response(self):
        # Grab latest values from source
        power = self.data_source.get_power()
        current = self.data_source.get_current()
        voltage = self.data_source.voltage

        # Response dict
        response = {
            "emeter": {
                "get_realtime": {
                    "current": current,
                    "voltage": voltage,
                    "power": power,
                    "total": 0,     # Unsure if this needs a value, appears not to
                    "err_code": 0   # No errors here!
                }
            },
            "system": {
                "get_sysinfo": {
                    "err_code": 0,
                    "sw_ver": "1.2.5 Build 171206 Rel.085954",
                    "hw_ver": "1.0",
                    "type": "IOT.SMARTPLUGSWITCH",
                    "model": "HS110(US)",
                    "mac": self.mac.upper(),
                    "deviceId": self.device_id.upper(),
                    "hwId": "60FF6B258734EA6880E186F8C96DDC61",
                    "fwId": "00000000000000000000000000000000",
                    "oemId": "FFF22CFF774A0B89F7624BFC6F50D5DE",
                    "alias": self.alias,
                    "dev_name": "Wi-Fi Smart Plug With Energy Monitoring",
                    "icon_hash": "",
                    "relay_state": 1,  # Assuming it's on, not sure it matters
                    "on_time": time() - self.start_time,
                    "active_mode": "none",
                    "feature": "TIM:ENE",
                    "updating": 0,
                    "rssi": -60,    # Great wifi signal
                    "led_off": 0,   # Probably not important
                    "latitude": 39.8283,    # Center of the US
                    "longitude": -98.5795   # Center of the US
                }
            }
        }
        return response


if __name__ == "__main__":
    # Convenience function to generate a MAC address and Device ID
    gen_device_id = generate_deviceid()
    print(f"Generated Device ID:   {gen_device_id.upper()}")
    gen_mac = generate_mac(oui='50:c7:bf')
    print(f"Generated MAC:         {gen_mac.upper()}")