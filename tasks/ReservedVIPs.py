import ipcalc
from pydantic_yaml import YamlModel

from tasks.constellation_v01 import VipType


class ReservedVIPs(YamlModel):
    public_ipv4: list = []
    global_ipv4: list = []

    def extend(self, reservation: list):
        for item in reservation:
            network = ipcalc.Network('{}/{}'.format(item['address'], item['cidr']))
            ipv4 = str(network.to_ipv4()).split('/')[0]  # ToDo: Bug? .to_ipv4() should return only the address.
            if item['type'] == VipType.global_ipv4:
                self.global_ipv4.append(ipv4)
            elif item['type'] == VipType.public_ipv4:
                self.public_ipv4.append(ipv4)
            else:
                print("Equinix Metal API changed the type of VIP: {}, is not supported".format(item['type']))
