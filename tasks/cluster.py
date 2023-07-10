import glob
import os
import re
import shutil

import yaml
from invoke import task

from tasks.controllers.ClusterCtrl import ClusterCtrl
from tasks.controllers.ClusterctlCtrl import ClusterctlCtrl
from tasks.dao.ProjectPaths import RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.gocy import context_set_kind, context_set_bary
from tasks.helpers import str_presenter, get_secrets_dir, \
    get_cp_vip_address, get_constellation_clusters, get_cluster_spec, \
    get_constellation, get_argo_infra_namespace_name, user_confirmed
from tasks.metal import register_vips
from tasks.models.ConstellationSpecV01 import Constellation

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


def clean_constellation_dir():
    files_to_remove = glob.glob(
        os.path.join(
            get_secrets_dir(),
            '**'),
        recursive=True)
    files_to_remove = list(map(lambda file_name: re.sub("/$", "", file_name), files_to_remove))

    whitelisted_files = [
        get_secrets_dir(),
        os.path.join(get_secrets_dir(), 'secrets')
    ]
    whitelisted_files = list(map(lambda file_name: re.sub("/$", "", file_name), whitelisted_files))

    files_to_remove = list(set(files_to_remove) - set(whitelisted_files))
    if len(files_to_remove) == 0:
        return

    print('Following files will be removed:')
    for file in files_to_remove:
        print(file)

    if user_confirmed():
        for name in files_to_remove:
            try:
                if os.path.isfile(name):
                    os.remove(name)
                else:
                    shutil.rmtree(name)
            except OSError:
                pass


def clean_k8s_contexts(ctx, constellation: Constellation):
    contexts = set([line.strip() for line in ctx.run("kconf list", hide='stdout', echo=True).stdout.splitlines()])
    trash_can = set()
    clusters = get_constellation_clusters(constellation)
    for context in contexts:
        for cluster in clusters:
            if "@" + cluster.name in context:
                trash_can.add(context)

    if len(trash_can) == 0:
        return

    print('Following k8s contexts will be removed:')
    for trash in trash_can:
        print(trash)

    if user_confirmed():
        difference = contexts.difference(trash_can)
        ctx.run("kconf use " + difference.pop())
        for trash in trash_can:
            ctx.run("kconf rm " + trash.replace('*', '').strip(), echo=True, pty=True)


@task()
def clean(ctx):
    """
    USE WITH CAUTION! - Nukes constellation configuration.
    """
    constellation = get_constellation()
    clean_constellation_dir()
    clean_k8s_contexts(ctx, constellation)


# @task(clean, context_set_kind, generate_cpem_config, register_vips,
#       render_capi_cluster_manifest, talos_apply_config_patches)
@task()
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

@task()
def toster(ctx):
    state = SystemContext()
    for cluster in state.constellation:
        print(cluster)