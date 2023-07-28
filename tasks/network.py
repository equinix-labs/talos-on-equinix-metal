import base64
import json
import os
from typing import Union

import yaml
from invoke import task

from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter, get_secrets_dir, get_cp_vip_address, \
    get_cluster_spec_from_context
from tasks.models.ConstellationSpecV01 import Cluster, VipRole
from tasks.models.Namespaces import Namespace

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task()
def apply_kubespan_patch(ctx):
    """
    For some reason, Kubespan turns off once cilium is deployed.
    https://www.talos.dev/v1.4/kubernetes-guides/network/kubespan/
    Once the patch is applied kubespan is back up.
    """
    cluster_spec = get_cluster_spec_from_context(ctx)
    ctx.run("talosctl --context {} patch mc -p @patch-templates/kubespan/common.pt.yaml".format(
        cluster_spec.name
    ), echo=True)


@task()
def enable_cluster_mesh(ctx, echo: bool = False, namespace: Namespace = Namespace.network_services):
    """
    Enables Cilium ClusterMesh
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    state = SystemContext(ctx, echo)
    state.set_bary_cluster()

    connected_targets = list()
    for cluster in state.constellation:
        for cluster_b in state.constellation:
            if cluster.name != cluster_b.name and Union[cluster.name, cluster_b.name] not in connected_targets:
                # print("Connect {} => {}".format(cluster.name, cluster_b.name))
                ctx.run("cilium --namespace {} --context {} clustermesh connect --destination-context {}".format(
                    namespace.value,
                    'admin@' + cluster.name,
                    'admin@' + cluster_b.name
                ), echo=True)
                connected_targets.append(Union[cluster.name, cluster_b.name])

    for cluster in state.constellation:
        cluster_mesh_config_yaml = ctx.run(
            "kubectl --context admin@{} -n {} get secret cilium-clustermesh -o yaml".format(
                cluster.name,
                namespace,
            ), hide="stdout", echo=echo).stdout
        cluster_mesh_config = dict(yaml.safe_load(cluster_mesh_config_yaml))

        del(cluster_mesh_config['metadata']['creationTimestamp'])
        del(cluster_mesh_config['metadata']['resourceVersion'])
        del(cluster_mesh_config['metadata']['uid'])

        cluster_mesh_config_data_keys = cluster_mesh_config['data'].keys()
        for key in cluster_mesh_config_data_keys:
            if key in state.constellation:
                decoded_yaml = base64.b64decode(cluster_mesh_config['data'][key])
                endpoint_config = dict(yaml.safe_load(decoded_yaml))
                # print(cluster.name)
                # print(endpoint_config)
                metal_ctrl = MetalCtrl(state, echo, Cluster(name=key))
                endpoint_config['endpoints'][0] = "https://{}:2379".format(
                    metal_ctrl.get_vips(VipRole.mesh).public_ipv4[0])

                encoded_yaml = base64.b64encode(bytes(yaml.safe_dump(endpoint_config), 'utf-8')).decode('utf-8')
                cluster_mesh_config['data'][key] = encoded_yaml

        paths = ProjectPaths(constellation_name=state.constellation.name, cluster_name=cluster.name)
        with open(paths.patch_mesh_secret_file(), 'w') as cluster_mesh_secret_file:
            yaml.safe_dump(cluster_mesh_config, cluster_mesh_secret_file)

        ctx.run("kubectl --context admin@{} -n {} delete secret cilium-clustermesh".format(
            cluster.name,
            namespace
        ), echo=echo)

        ctx.run("kubectl --context admin@{} apply -f {}".format(
            cluster.name,
            paths.patch_mesh_secret_file()
        ), echo=echo)

        ctx.run("kubectl --context admin@{} --namespace {} rollout restart deployment/cilium-operator".format(
            cluster.name,
            namespace), echo=echo)

        ctx.run("kubectl --context admin@{} --namespace {} rollout restart daemonset/cilium".format(
            cluster.name,
            namespace), echo=echo)

        # titan-machine-m3-large-x86-hc4sq - 136.144.59.203