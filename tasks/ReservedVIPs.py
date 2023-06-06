from pprint import pprint

import ipcalc
from pydantic_yaml import YamlModel

from tasks.constellation_v01 import VipType


class ReservedVIPs(YamlModel):
    public_ipv4: list = []
    global_ipv4: list = []

    def append(self, reservation):
        ip_address = ipcalc.Network('{}/{}'.format(reservation['address'], reservation['cidr']))
        if reservation['type'] == VipType.global_ipv4:
            self.global_ipv4.append(str(ip_address))
        elif reservation['type'] == VipType.public_ipv4:
            self.public_ipv4.append(str(ip_address))
        else:
            print("Equinix Metal API changed the type of VIP: {}, is not supported".format(reservation['type']))
