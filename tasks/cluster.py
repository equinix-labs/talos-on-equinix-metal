import os

import yaml
from invoke import task

from tasks.controllers.ClusterCtrl import ClusterCtrl
from tasks.wrappers.Clusterctl import Clusterctl
from tasks.dao.ProjectPaths import RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter, get_secrets_dir, \
    get_constellation, get_argo_infra_namespace_name
from tasks.metal import register_vips
from tasks.models.Defaults import KIND_CLUSTER_NAME

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task(register_vips)
def talosctl_gen_config(ctx, echo: bool = False):
    """
    Produces initial Talos machine configuration, that later on will be patched with custom cluster settings.
    """
    state = SystemContext(ctx, echo)
    cluster_ctrl = ClusterCtrl(state, echo)
    cluster_ctrl.talosctl_gen_config(ctx)


@task()
def get_secrets(ctx, echo: bool = False):
    """
    Produces [secrets_dir]/[cluster_name].kubeconfig
    """
    state = SystemContext(ctx, echo)
    cluster_ctrl = ClusterCtrl(state, echo)
    cluster_ctrl.get_secrets(ctx)


@task()
def clean(ctx, echo: bool = False):
    """
    USE WITH CAUTION! - Nukes constellation configuration.
    """
    state = SystemContext(ctx, echo)
    cluster_ctrl = ClusterCtrl(state, echo)
    cluster_ctrl.delete_directories()
    cluster_ctrl.delete_k8s_contexts(ctx)
    cluster_ctrl.delete_talos_contexts()


@task(clean, register_vips)
def build_manifests(ctx, echo: bool = False, dev_mode: bool = False):
    """
    Produces cluster manifests
    """
    state = SystemContext(ctx, echo)
    state.set_bary_cluster()
    cluster_ctrl = ClusterCtrl(state, echo)
    cluster_ctrl.build_manifest(ctx, dev_mode)


@task()
def create(ctx, echo: bool = False):
    """
    Applies initial cluster manifest - the management cluster(CAPI) on local kind cluster.
    """
    context = SystemContext(ctx, echo)
    paths = context.project_paths
    repo_paths = RepoPaths()

    ctx.run("kubectl apply -f {}".format(
        repo_paths.templates_dir('argo', 'namespace.yaml')
    ))
    ctx.run("kubectl apply -f {}".format(
        paths.cluster_capi_static_manifest_file()), echo=echo)


@task()
def clusterctl_move(ctx, echo: bool = False):
    """
    Move CAPI objects from local kind cluster to the management(bary) cluster
    """
    state = SystemContext(ctx, echo)
    state.set_bary_cluster(state.constellation.bary.name)

    clusterctl = Clusterctl(state)
    clusterctl.init(ctx)

    state.set_bary_cluster(KIND_CLUSTER_NAME)

    constellation = get_constellation()
    bary_kubeconfig = os.path.join(
        get_secrets_dir(), constellation.bary.name, constellation.bary.name + '.kubeconfig')
    ctx.run("clusterctl --namespace {} move --to-kubeconfig={}".format(
        get_argo_infra_namespace_name(),
        bary_kubeconfig
    ), echo=True)
