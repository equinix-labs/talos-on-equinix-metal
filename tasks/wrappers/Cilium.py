import base64
from typing import Union

import yaml
from invoke import Context

from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster, VipRole
from tasks.models.Namespaces import Namespace


class Cilium:
    _state: SystemContext
    _cluster: Cluster
    _ctx: Context
    _echo: bool

    def __init__(self, ctx: Context, state: SystemContext, echo: bool):
        self._state = state
        self._ctx = ctx
        self._echo = echo

    def status(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            self._ctx.run("cilium --context admin@{} --namespace {} status".format(
                cluster.name,
                namespace
            ), echo=self._echo)

    def cluster_mesh_status(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            self._ctx.run("cilium --context admin@{} --namespace {} clustermesh status".format(
                cluster.name,
                namespace
            ), echo=self._echo)

    def cluster_mesh_connect(self, namespace: Namespace = Namespace.network_services):
        connected_targets = list()
        for cluster in self._state.constellation:
            for cluster_b in self._state.constellation:
                if cluster.name != cluster_b.name and Union[cluster.name, cluster_b.name] not in connected_targets:
                    # print("Connect {} => {}".format(cluster.name, cluster_b.name))
                    self._ctx.run("cilium --namespace {} --context {} clustermesh connect --destination-context {}".format(
                        namespace.value,
                        'admin@' + cluster.name,
                        'admin@' + cluster_b.name
                    ), echo=self._echo)
                    connected_targets.append(Union[cluster.name, cluster_b.name])

        for cluster in self._state.constellation:
            cluster_mesh_config_yaml = self._ctx.run(
                "kubectl --context admin@{} -n {} get secret cilium-clustermesh -o yaml".format(
                    cluster.name,
                    namespace,
                ), hide="stdout", echo=self._echo).stdout
            cluster_mesh_config = dict(yaml.safe_load(cluster_mesh_config_yaml))

            del (cluster_mesh_config['metadata']['creationTimestamp'])
            del (cluster_mesh_config['metadata']['resourceVersion'])
            del (cluster_mesh_config['metadata']['uid'])

            cluster_mesh_config_data_keys = cluster_mesh_config['data'].keys()
            for key in cluster_mesh_config_data_keys:
                if key in self._state.constellation:
                    decoded_yaml = base64.b64decode(cluster_mesh_config['data'][key])
                    endpoint_config = dict(yaml.safe_load(decoded_yaml))
                    # print(cluster.name)
                    # print(endpoint_config)
                    # metal_ctrl = MetalCtrl(self._state, self._echo, Cluster(name=key))
                    endpoint_config['endpoints'] = [
                        "https://{}:2379".format(
                            get_fqdn(['mesh', key], self._state.secrets, cluster))
                        # "https://{}:2379".format(
                        #     metal_ctrl.get_vips(VipRole.mesh).public_ipv4[0]),
                        # "https://clustermesh-apiserver.{}.svc:2379".format(namespace)
                    ]

                    encoded_yaml = base64.b64encode(bytes(yaml.safe_dump(endpoint_config), 'utf-8')).decode('utf-8')
                    cluster_mesh_config['data'][key] = encoded_yaml

            paths = ProjectPaths(constellation_name=self._state.constellation.name, cluster_name=cluster.name)
            with open(paths.patch_mesh_secret_file(), 'w') as cluster_mesh_secret_file:
                yaml.safe_dump(cluster_mesh_config, cluster_mesh_secret_file)

            self._ctx.run("kubectl --context admin@{} -n {} delete secret cilium-clustermesh".format(
                cluster.name,
                namespace
            ), echo=self._echo)

            self._ctx.run("kubectl --context admin@{} apply -f {}".format(
                cluster.name,
                paths.patch_mesh_secret_file()
            ), echo=self._echo)

            self.restart(namespace)

    def restart(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            self._ctx.run("kubectl --context admin@{} --namespace {} rollout restart deployment/cilium-operator".format(
                cluster.name,
                namespace), echo=self._echo)

            self._ctx.run("kubectl --context admin@{} --namespace {} rollout restart deployment/clustermesh-apiserver".format(
                cluster.name,
                namespace), echo=self._echo)

            self._ctx.run("kubectl --context admin@{} --namespace {} rollout restart daemonset/cilium".format(
                cluster.name,
                namespace), echo=self._echo)

    def cluster_mesh_disconnect(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            for cluster_b in self._state.constellation:
                if cluster.name != cluster_b.name:
                    self._ctx.run(
                        "cilium --context admin@{} --namespace {} clustermesh "
                        "disconnect --destination-context admin@{}".format(
                            cluster.name,
                            namespace,
                            cluster_b.name
                        ),
                        echo=self._echo)

        self.restart(namespace)