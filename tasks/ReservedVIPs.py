from pprint import pprint

import ipcalc
from pydantic_yaml import YamlModel

from tasks.constellation_v01 import VipType


class ReservedVIPs(YamlModel):
    public_ipv4: list = []
    global_ipv4: list = []

    def extend(self, reservation: list):
        for item in reservation:
            if type(item) is dict:
                ip_address = ipcalc.Network('{}/{}'.format(item['address'], item['cidr']))
                if item['type'] == VipType.global_ipv4:
                    self.global_ipv4.append(str(ip_address))
                elif item['type'] == VipType.public_ipv4:
                    self.public_ipv4.append(str(ip_address))
                else:
                    print("Equinix Metal API changed the type of VIP: {}, is not supported".format(item['type']))
