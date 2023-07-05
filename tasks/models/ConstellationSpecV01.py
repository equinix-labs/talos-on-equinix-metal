from typing import Optional, Any

from pydantic_yaml import YamlStrEnum, YamlModel


class VipType(YamlStrEnum):
    public_ipv4 = 'public_ipv4'
    global_ipv4 = 'global_ipv4'


class VipRole(YamlStrEnum):
    cp = 'cp'
    ingress = 'ingress'
    mesh = 'mesh'


class Vip(YamlModel):
    role: VipRole = None
    count: int = 0
    vipType: VipType = None
    reserved: list[dict] = list()


class Node(YamlModel):
    count: int = 0
    plan: str = ''


class Cluster(YamlModel):
    name: str = ''
    metro: str = ''
    cpem: str = ''
    talos: str = ''
    kubernetes: str = ''
    domain_prefix: str = ''
    pod_cidr_blocks: list[str] = []
    service_cidr_blocks: list[str] = []
    vips: list[Vip] = []
    control_nodes: list[Node] = []
    worker_nodes: list[Node] = []


class Constellation(YamlModel):
    index: Optional[int] = -1

    # https://docs.pydantic.dev/latest/
    name: str = 'name'
    capi: str = 'capi'
    cabpt: str = 'cabpt'
    cacppt: str = 'cacppt'
    capp: str = 'capp'
    version: str = 'version'
    bary: Cluster = None
    satellites: list[Cluster] = []

    def __contains__(self, cluster: Any):
        if type(cluster) is Cluster:
            cluster_name = cluster.name
        else:
            cluster_name = cluster

        if self.bary.name == cluster_name:
            return True

        for satellite in self.satellites:
            if satellite.name == cluster_name:
                return True

        return False

    def __iter__(self):
        return self

    def __next__(self) -> Cluster:
        if self.index < 0:
            self.index += 1
            return self.bary
        else:
            # ToDo: FIX THIS !!! There has to be a better way to pull an element from list by index; Facepalm :(((
            count = len(self.satellites)
            if self.index >= count:
                raise StopIteration

            for index, item in enumerate(self.satellites):
                if index == self.index:
                    self.index += 1
                    return item
