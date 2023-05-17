from pydantic import BaseModel
from pydantic_yaml import YamlStrEnum, YamlModel


class VipType(YamlStrEnum):
    public_ipv4 = 'public_ipv4'
    global_ipv4 = 'global_ipv4'


class VipRole(YamlStrEnum):
    cp = 'cp'
    ingress = 'ingress'
    mesh = 'mesh'


class Vip(BaseModel):
    role: VipRole = None
    count: int = 0
    vipType: VipType = None


class Node(BaseModel):
    count: int = 0
    plan: str = ''


class Cluster(BaseModel):
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
    # https://docs.pydantic.dev/latest/
    name: str = 'name'
    capi: str = 'capi'
    cabpt: str = 'cabpt'
    cacppt: str = 'cacppt'
    capp: str = 'capp'
    version: str = 'version'
    bary: Cluster = None
    satellites: list[Cluster] = []

