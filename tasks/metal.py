import json
import os

import yaml
from invoke import task

from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter, get_secrets_dir, \
    get_cpem_config, get_constellation

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task()
def generate_cpem_config(ctx, cpem_config_file_name="cpem/cpem.yaml"):
    """
    Produces [secrets_dir]/cpem/cpem.yaml - 'Cloud Provider for Equinix Metal' config spec
    """
    cpem_config = get_cpem_config()
    ctx.run("mkdir -p {}".format(
        os.path.join(
            get_secrets_dir(),
            'cpem'
        )
    ), echo=True)

    command = "kubectl create -o yaml \
    --dry-run='client' secret generic -n kube-system metal-cloud-config \
    --from-literal='cloud-sa.json={}'"

    print(command.format('[REDACTED]'))
    k8s_secret = ctx.run(command.format(
        json.dumps(cpem_config)
    ), hide='stdout', echo=False)

    yaml_k8s_secret = yaml.safe_load(k8s_secret.stdout)
    del yaml_k8s_secret['metadata']['creationTimestamp']

    with open(os.path.join(get_secrets_dir(), cpem_config_file_name), 'w') as cpem_config_file:
        yaml.dump(yaml_k8s_secret, cpem_config_file)


# @task(create_config_dirs)
@task()
def register_vips(ctx, echo: bool = False):
    """
    Registers VIPs as per constellation spec in ~/.gocy/[constellation_name].constellation.yaml
    """
    state = SystemContext()
    metal_ctrl = MetalCtrl(state, echo)
    metal_ctrl.register_vips(ctx)


@task()
def list_facilities(ctx):
    """
    Wrapper for 'metal facilities get'
    """
    ctx.run('metal facilities get', echo=True)


@task()
def check_capacity(ctx):
    """
    Check device capacity for clusters specified in invoke.yaml
    """
    nodes_total = dict()
    constellation = get_constellation()
    bary_metro = constellation.bary.metro
    nodes_total[bary_metro] = dict()
    bary_nodes = constellation.bary.control_nodes
    bary_nodes.extend(constellation.bary.worker_nodes)

    for node in bary_nodes:
        if node.plan not in nodes_total[bary_metro]:
            nodes_total[bary_metro][node.plan] = node.count
        else:
            nodes_total[bary_metro][node.plan] = nodes_total[bary_metro][node.plan] + node.count

    for satellite in constellation.satellites:
        if satellite.metro not in nodes_total:
            nodes_total[satellite.metro] = dict()

        satellite_nodes = satellite.worker_nodes
        satellite_nodes.extend(satellite.control_nodes)
        for node in satellite_nodes:
            if node.plan not in nodes_total[satellite.metro]:
                nodes_total[satellite.metro][node.plan] = node.count
            else:
                nodes_total[satellite.metro][node.plan] = nodes_total[satellite.metro][node.plan] + node.count

    for metro in nodes_total:
        for node_type, count in nodes_total[metro].items():
            ctx.run("metal capacity check --metros {} --plans {} --quantity {}".format(
                metro, node_type, count
            ), echo=True)
