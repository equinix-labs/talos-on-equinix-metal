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
    nodes: Optional[list[Node]] = []
    node_index: Optional[int] = 0

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

    def __iter__(self):
        self.nodes = list()
        for node in self.control_nodes:
            for index in range(node.count):
                self.nodes.append(Node(count=1, plan=node.plan))

        for node in self.worker_nodes:
            for index in range(node.count):
                self.nodes.append(Node(count=1, plan=node.plan))

        self.node_index = 0
        return self

    def __next__(self):
        if self.node_index >= len(self.nodes):
            raise StopIteration

        item = self.nodes.__getitem__(self.node_index)
        self.node_index += 1
        return item


class Constellation(YamlModel):
    cluster_index: Optional[int] = 0
    clusters: Optional[list[Cluster]] = []

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
        self.clusters = [self.bary]
        self.clusters.extend(self.satellites)
        return self

    def __next__(self) -> Cluster:
        if self.cluster_index >= len(self.clusters):
            raise StopIteration

        item = self.clusters.__getitem__(self.cluster_index)
        self.cluster_index += 1
        return item


