from yamlable import yaml_info, YamlAble


@yaml_info(yaml_tag_ns='v01')
class VipType(YamlAble):
    public_ipv4 = 'public_ipv4'
    global_ipv4 = 'global_ipv4'


@yaml_info(yaml_tag_ns='v01')
class VipRole(YamlAble):
    cp = 'cp'
    ingress = 'ingress'
    mesh = 'mesh'


@yaml_info(yaml_tag_ns='v01')
class Vip(YamlAble):
    def __init__(self, role: VipRole, count: int, vip: VipType):
        self.role = role
        self.count = count
        self.vip = vip


@yaml_info(yaml_tag_ns='v01')
class Node(YamlAble):
    def __init__(self, count: int, plan: str):
        self.count = count
        self.plan = plan


@yaml_info(yaml_tag_ns='v01')
class Cluster(YamlAble):
    def __init__(
            self,
            name: str,
            metro: str,
            cpem: str,
            pod_cidr_blocks: list[str],
            service_cidr_blocks: list[str],
            vips: list[Vip],
            control_nodes: list[Node],
            worker_nodes: list[Node]
    ):
        self.name = name
        self.pod_cidr_blocks = pod_cidr_blocks
        self.service_cidr_blocks = service_cidr_blocks
        self.metro = metro
        self.cpem = cpem
        self.vips = vips
        self.control_nodes = control_nodes
        self.worker_nodes = worker_nodes


@yaml_info(yaml_tag_ns='v01')
class Constellation(YamlAble):
    def __init__(
            self,
            name: str,
            capi: str,
            cabpt: str,
            cacppt: str,
            capp: str,
            version: str,
            bary: Cluster,
            satellites: [Cluster]
    ):
        self.name = name
        self.capi = capi
        self.cabpt = cabpt
        self.cacppt = cacppt
        self.capp = capp
        self.bary = bary
        self.version = version
        self.satellites = satellites

