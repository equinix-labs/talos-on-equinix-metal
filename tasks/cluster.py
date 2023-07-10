import os

import yaml
from invoke import task

from tasks.controllers.ClusterCtrl import ClusterCtrl
from tasks.controllers.ClusterctlCtrl import ClusterctlCtrl
from tasks.dao.ProjectPaths import RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.gocy import context_set_kind, context_set_bary
from tasks.helpers import str_presenter, get_secrets_dir, \
    get_cp_vip_address, get_constellation_clusters, get_constellation, get_argo_infra_namespace_name
from tasks.metal import register_vips

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task(register_vips)
def talosctl_gen_config(ctx):
    """
    Produces initial Talos machine configuration, that later on will be patched with custom cluster settings.
    """
    for cluster_spec in get_constellation_clusters():
        cluster_spec_dir = os.path.join(get_secrets_dir(), cluster_spec.name)
        with ctx.cd(cluster_spec_dir):
            ctx.run(
                "talosctl gen config {} https://{}:6443 | true".format(
                    cluster_spec.name,
                    get_cp_vip_address(cluster_spec)
                ),
                echo=True
            )


@task()
def get_cluster_secrets(ctx, echo: bool = False):
    """
    Produces [secrets_dir]/[cluster_name].kubeconfig
    """
    state = SystemContext()
    cluster_ctrl = ClusterCtrl(state, echo)
    cluster_ctrl.get_secrets(ctx)


@task()
def clean(ctx, echo: bool = False):
    """
    USE WITH CAUTION! - Nukes constellation configuration.
    """
    state = SystemContext()
    cluster_ctrl = ClusterCtrl(state, echo)
    cluster_ctrl.delete_directories()
    cluster_ctrl.delete_k8s_contexts(ctx)
    cluster_ctrl.delete_talos_contexts(ctx)


@task(clean, context_set_kind, register_vips)
def build_manifests(ctx, echo: bool = False, dev_mode: bool = False):
    """
    Produces cluster manifests
    """
    state = SystemContext()
    cluster_ctrl = ClusterCtrl(state, echo)
    cluster_ctrl.build_manifest(ctx, dev_mode)


@task()
def create(ctx, echo: bool = False):
    """
    Applies initial cluster manifest - the management cluster(CAPI) on local kind cluster.
    """
    context = SystemContext()
    paths = context.project_paths
    repo_paths = RepoPaths()

    ctx.run("kubectl apply -f {}".format(
        repo_paths.templates_dir('argo', 'namespace.yaml')
    ))
    ctx.run("kubectl apply -f {}".format(
        paths.cluster_capi_static_manifest_file()), echo=echo)


@task()
def clusterctl_move(ctx):
    """
    Move CAPI objects from local kind cluster to the management(bary) cluster
    """
    state = SystemContext()
    context_set_bary(ctx)  # ToDo remove

    clusterctl = ClusterctlCtrl(state)
    clusterctl.init(ctx)

    context_set_kind(ctx)  # ToDo remove

    constellation = get_constellation()
    bary_kubeconfig = os.path.join(
        get_secrets_dir(), constellation.bary.name, constellation.bary.name + '.kubeconfig')
    ctx.run("clusterctl --namespace {} move --to-kubeconfig={}".format(
        get_argo_infra_namespace_name(),
        bary_kubeconfig
    ), echo=True)
