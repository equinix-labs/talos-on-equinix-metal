import yaml
from invoke import task

from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter, get_constellation
from tasks.wrappers.Kubectl import Kubectl

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


# @task(create_config_dirs)
@task()
def register_vips(ctx, echo: bool = False):
    """
    Registers VIPs as per constellation spec in ~/.gocy/[constellation_name].constellation.yaml
    """
    state = SystemContext(ctx, echo)
    metal_ctrl = MetalCtrl(state, echo)
    metal_ctrl.register_vips(ctx)


@task()
def test(ctx, echo=True):
    state = SystemContext(ctx, echo)
    kubectl = Kubectl(ctx, state, echo)
    print(kubectl.get_nodes_eip())


@task()
def bgp_fix(ctx, echo: bool = False):
    """
    Registers VIPs as per constellation spec in ~/.gocy/[constellation_name].constellation.yaml
    """
    state = SystemContext(ctx, echo)
    metal_ctrl = MetalCtrl(state, echo)
    metal_ctrl.hack_fix_bgp_peer_routs(ctx)


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
