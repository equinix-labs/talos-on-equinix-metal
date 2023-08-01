import yaml
from invoke import task

from tasks.controllers.ClusterCtrl import ClusterCtrl
from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.ProjectPaths import RepoPaths, ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter
from tasks.models.Defaults import KIND_CLUSTER_NAME
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Clusterctl import Clusterctl

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task()
def boot(ctx, cluster_name: str, echo: bool = False):
    """
    Produces [secrets_dir]/[cluster_name].kubeconfig
    """
    state = SystemContext(ctx, echo)
    cluster_ctrl = ClusterCtrl(state, state.cluster(cluster_name), echo)
    cluster_ctrl.get_secrets(ctx)


@task()
def oidc_kubeconfig(ctx, cluster_name: str, echo: bool = False):
    """
    Produces [secrets_dir]/[cluster_name].oidc.kubeconfig
    """
    state = SystemContext(ctx, echo)
    cluster_ctrl = ClusterCtrl(state, state.cluster(cluster_name), echo)
    cluster_ctrl.get_oidc_kubeconfig()


@task()
def clean(ctx, cluster_name: str, echo: bool = False):
    """
    USE WITH CAUTION! - Nukes constellation configuration.
    """
    state = SystemContext(ctx, echo)
    cluster_ctrl = ClusterCtrl(state, state.cluster(cluster_name), echo)
    cluster_ctrl.delete_directories()
    cluster_ctrl.delete_k8s_contexts(ctx)
    cluster_ctrl.delete_talos_contexts()


@task()
def manifest(ctx, cluster_name: str, echo: bool = False, dev_mode: bool = False):
    """
    Produces cluster CAPI manifest
    """
    state = SystemContext(ctx, echo)
    state.set_bary_cluster()

    cluster_ctrl = ClusterCtrl(state, state.cluster(cluster_name), echo)

    cluster_ctrl.delete_directories()
    cluster_ctrl.delete_k8s_contexts(ctx)
    cluster_ctrl.delete_talos_contexts()

    metal_ctrl = MetalCtrl(state, echo, state.cluster(cluster_name))
    metal_ctrl.register_vips(ctx)

    cluster_ctrl.build_manifest(ctx, dev_mode)


@task()
def create(ctx, cluster_name: str, echo: bool = False):
    """
    Applies initial cluster manifest - the management cluster(CAPI) on local kind cluster.
    """
    context = SystemContext(ctx, echo)
    paths = ProjectPaths(context.constellation.name, context.cluster(cluster_name).name)
    repo_paths = RepoPaths()

    ctx.run("kubectl apply -f {}".format(
        repo_paths.templates_dir('argo', 'namespace.yaml')
    ))
    ctx.run("kubectl apply -f {}".format(
        paths.cluster_capi_static_manifest_file()), echo=echo)


@task()
def move(ctx, echo: bool = False):
    """
    Move CAPI objects from local kind cluster to the management(bary) cluster
    """
    state = SystemContext(ctx, echo)
    state.set_bary_cluster(state.constellation.bary.name)

    clusterctl = Clusterctl(state)
    clusterctl.init(ctx)

    state.set_bary_cluster(KIND_CLUSTER_NAME)

    constellation = state.constellation
    bary_kubeconfig = ProjectPaths(constellation.name, constellation.bary.name).kubeconfig_file()
    ctx.run("clusterctl --namespace {} move --to-kubeconfig={}".format(
        Namespace.argocd,
        bary_kubeconfig
    ), echo=True)

    state.set_bary_cluster(state.constellation.bary.name)
    state.set_cluster(state.constellation.bary)

    cluster_ctrl = ClusterCtrl(state, state.constellation.bary, echo)
    cluster_ctrl.crete_missing_talosconfig(ctx)
