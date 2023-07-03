import os

from tasks.models.ConstellationSpecV01 import Constellation, Cluster, VipType, Vip, VipRole, Node


def get_demo_constellation_file_name():
    return os.path.join('templates', 'jupiter.constellation.yaml')


def get_demo_constellation():
    return Constellation(
        name='demo',
        capi='v1.4.2',
        cabpt='v0.6.0',
        cacppt='v0.5.0',
        capp='v0.7.1',
        version='0.1.0',
        bary=Cluster(
            name='jupiter',
            metro='pa',
            cpem='v3.6.1',
            pod_cidr_blocks=['172.16.0.0/17'],
            service_cidr_blocks=['172.16.128.0/17'],
            vips=[
                Vip(role=VipRole.cp, count=1, vipType=VipType.public_ipv4),
                Vip(role=VipRole.ingress, count=1, vipType=VipType.public_ipv4),
                Vip(role=VipRole.mesh, count=1, vipType=VipType.public_ipv4)
            ],
            control_nodes=[
                Node(count=3, plan='m3.large.x86')
            ],
            worker_nodes=[
                Node(count=3, plan='m3.large.x86')
            ]
        ),
        satellites=[
            Cluster(
                name='ganymede',
                metro='md',
                cpem='v3.6.1',
                pod_cidr_blocks=['172.17.0.0/17'],
                service_cidr_blocks=['172.17.128.0/17'],
                vips=[
                    Vip(role=VipRole.cp, count=1, vipType=VipType.public_ipv4),
                    Vip(role=VipRole.ingress, count=1, vipType=VipType.global_ipv4),
                    Vip(role=VipRole.mesh, count=1, vipType=VipType.public_ipv4)
                ],
                control_nodes=[
                    Node(count=3, plan='m3.large.x86')
                ],
                worker_nodes=[
                    Node(count=3, plan='c3.medium.x86')
                ]
            ),
            Cluster(
                name='callisto',
                metro='fr',
                cpem='v3.6.1',
                pod_cidr_blocks=['172.18.0.0/17'],
                service_cidr_blocks=['172.18.128.0/17'],
                vips=[
                    Vip(role=VipRole.cp, count=1, vipType=VipType.public_ipv4),
                    Vip(role=VipRole.ingress, count=1, vipType=VipType.global_ipv4),
                    Vip(role=VipRole.mesh, count=1, vipType=VipType.public_ipv4)
                ],
                control_nodes=[
                    Node(count=3, plan='m3.large.x86')
                ],
                worker_nodes=[
                    Node(count=3, plan='c3.medium.x86')
                ]
            )
        ]
    )


def test_constellation_is_writeable(tmp_path):
    # https://github.com/NowanIlfideme/pydantic-yaml/tree/v0.11.2
    demo = get_demo_constellation()
    with open(os.path.join(tmp_path, 'config.yaml'), 'w') as cfg_file:
        cfg_file.write(demo.yaml())


def test_constellation_is_loadable():
    with open(get_demo_constellation_file_name()) as cfg_file:
        constellation = Constellation.parse_raw(cfg_file.read())

        assert type(constellation).__module__ == 'tasks.models.ConstellationSpecV01'
        assert type(constellation).__name__ == 'Constellation'


def test_constellation_knows_contains():
    callisto = Cluster(name='callisto')
    assert callisto in get_demo_constellation()


def test_constellation_can_iterate():
    demo = get_demo_constellation()
    assert 3 == len(list(demo))
    for index, cluster in enumerate(get_demo_constellation()):
        if index == 0:
            assert cluster.name == 'jupiter'
        if index == 1:
            assert cluster.name == 'ganymede'
        if index == 3:
            assert cluster.name == 'callisto'