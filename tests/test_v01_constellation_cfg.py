import os

import yaml

from tasks.constellation_v01 import Constellation, Cluster, VipType, Vip, VipRole, Node


def test_constellation_is_writeable():
    demo = Constellation(
        name='demo',
        capi='v1.4.2',
        cabpt='v0.6.0',
        cacppt='v0.5.0',
        capp='v0.7.1',
        version='0.1.0',
        bary=Cluster(
            'jupiter',
            'pa',
            'v3.6.1',
            ['172.16.0.0/17'],
            ['172.16.128.0/17'],
            [
                Vip(VipRole.cp, 1, VipType.public_ipv4),
                Vip(VipRole.ingress, 1, VipType.public_ipv4),
                Vip(VipRole.mesh, 1, VipType.public_ipv4)
            ],
            control_nodes=[
                Node(1, 'm3.small.x86')
            ],
            worker_nodes=[
                Node(1, 'm3.small.x86')
            ]
        ),
        satellites=[
            Cluster(
                'ganymede',
                'md',
                'v3.6.1',
                ['172.17.0.0/17'],
                ['172.17.128.0/17'],
                [
                    Vip(VipRole.cp, 1, VipType.public_ipv4),
                    Vip(VipRole.ingress, 1, VipType.global_ipv4),
                    Vip(VipRole.mesh, 1, VipType.public_ipv4)
                ],
                control_nodes=[
                    Node(1, 'm3.small.x86')
                ],
                worker_nodes=[
                    Node(1, 'm3.small.x86')
                ]
            ),
            Cluster(
                'callisto',
                'fr',
                'v3.6.1',
                ['172.18.0.0/17'],
                ['172.18.128.0/17'],
                [
                    Vip(VipRole.cp, 1, VipType.public_ipv4),
                    Vip(VipRole.ingress, 1, VipType.global_ipv4),
                    Vip(VipRole.mesh, 1, VipType.public_ipv4)
                ],
                control_nodes=[
                    Node(1, 'm3.small.x86')
                ],
                worker_nodes=[
                    Node(1, 'm3.small.x86')
                ]
            )
        ]
    )
    with open(os.path.join('tests', 'c.yaml'), 'w') as cfg_file:
        demo.dump_yaml(cfg_file)


def test_constellation_is_loadable():
    with open(os.path.join('tests', 'demo.v0.1.constellation.yaml')) as cfg_file:
        constellation = Constellation.load_yaml(cfg_file)

        assert type(constellation).__module__ == 'tasks.constellation_v01'
        assert type(constellation).__name__ == 'Constellation'


