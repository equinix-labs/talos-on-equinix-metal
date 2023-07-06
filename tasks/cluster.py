import glob
import os
import re
import shutil

import yaml
from invoke import task

from tasks.controllers.ClusterCtrl import ClusterCtrl
from tasks.controllers.ClusterctlCtrl import ClusterctlCtrl
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.gocy import context_set_kind, context_set_bary
from tasks.helpers import str_presenter, get_secrets_dir, \
    get_cp_vip_address, get_constellation_clusters, get_cluster_spec, \
    get_constellation, get_argo_infra_namespace_name, user_confirmed
from tasks.metal import register_vips
from tasks.models.ConstellationSpecV01 import Constellation

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump

_CLUSTER_MANIFEST_STATIC_FILE_NAME = "cluster-manifest.static-config.yaml"


# @task(register_vips, context_set_kind)
# @task()
# def render_capi_cluster_manifest(ctx):
#     """
#     Produces ClusterAPI manifest - ~/.gocy/[Constellation_name][Cluster_name]/cluster_spec.yaml
#     In this particular case we are dealing with two kind of config specifications. Cluster API one
#     and Talos Linux one. As per official CAPI documentation https://cluster-api.sigs.k8s.io/tasks/using-kustomize.html,
#     this functionality is currently limited. As of now Kustomize alone can not produce satisfactory result.
#     This is why we go with some custom python + jinja template solution.
#     """
#     repo_paths = RepoPaths()
#     project_paths = ProjectPaths()
#
#     with open(repo_paths.capi_control_plane_template()) as cluster_file:
#         capi_control_plane_template_yaml = cluster_file.read()
#
#     with open(repo_paths.capi_machines_template()) as md_file:
#         capi_machines_template_yaml = md_file.read()
#
#     secrets = get_secret_envs()
#     constellation = get_constellation()
#
#     for cluster_cfg in get_constellation_clusters(constellation):
#         data = {
#                 'TOEM_CPEM_SECRET': get_cpem_config_yaml(),
#                 'TOEM_CP_ENDPOINT': get_cp_vip_address(cluster_cfg),
#                 'SERVICE_DOMAIN': "{}.local".format(cluster_cfg.name),
#                 'CLUSTER_NAME': cluster_cfg.name,
#                 'METRO': cluster_cfg.metro,
#                 'CONTROL_PLANE_NODE_TYPE': cluster_cfg.control_nodes[0].plan,
#                 'CONTROL_PLANE_MACHINE_COUNT': cluster_cfg.control_nodes[0].count,
#                 'TALOS_VERSION': cluster_cfg.talos,
#                 'CPEM_VERSION': cluster_cfg.cpem,
#                 'KUBERNETES_VERSION': cluster_cfg.kubernetes,
#                 'namespace': get_argo_infra_namespace_name()
#             }
#         data.update(secrets)
#
#         jinja = get_jinja()
#         cluster_yaml_tpl = jinja.from_string(capi_control_plane_template_yaml)
#         cluster_yaml = cluster_yaml_tpl.render(data)
#
#         for worker_node in cluster_cfg.worker_nodes:
#             worker_yaml_tpl = jinja.from_string(capi_machines_template_yaml)
#             data['machine_name'] = "{}-machine-{}".format(
#                 cluster_cfg.name,
#                 worker_node.plan.replace('.', '-'))  # ToDo: CPEM blows up if there are dots in machine name
#             data['WORKER_NODE_TYPE'] = worker_node.plan
#             data['WORKER_MACHINE_COUNT'] = worker_node.count
#             cluster_yaml = "{}\n{}".format(cluster_yaml, worker_yaml_tpl.render(data))
#
#         cluster_spec = list(yaml.safe_load_all(cluster_yaml))
#
#         patch_cluster_spec_network(cluster_cfg, cluster_spec)
#
#         with open(project_paths.cluster_capi_manifest_file(), 'w') as cluster_template_file:
#             yaml.dump_all(cluster_spec, cluster_template_file)


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


# def _talos_apply_config_patch(ctx, cluster_spec: Cluster):
#     project_paths = ProjectPaths()
#
#     cluster_secrets_dir = get_cluster_secrets_dir(cluster_spec)
#     cluster_manifest_file_name = project_paths.cluster_capi_manifest_file()
#     # ToDo: Fix Magic strings in path
#     cluster_manifest_static_file_name = os.path.join(
#         cluster_secrets_dir, 'argo', 'infra', _CLUSTER_MANIFEST_STATIC_FILE_NAME)
#
#     constellation_create_dirs(cluster_spec)
#
#     with open(cluster_manifest_file_name) as cluster_manifest_file:
#         for document in yaml.safe_load_all(cluster_manifest_file):
#             if document['kind'] == 'TalosControlPlane':
#                 with open(os.path.join(cluster_secrets_dir, 'controlplane-patches.yaml'), 'w') as cp_patches_file:
#                     yaml.dump(
#                         document['spec']['controlPlaneConfig']['controlplane']['configPatches'],
#                         cp_patches_file
#                     )
#             if document['kind'] == 'TalosConfigTemplate':
#                 with open(os.path.join(cluster_secrets_dir, 'worker-patches.yaml'), 'w') as worker_patches_file:
#                     yaml.dump(
#                         document['spec']['template']['spec']['configPatches'],
#                         worker_patches_file
#                     )
#
#     with ctx.cd(cluster_secrets_dir):
#         worker_capi_file_name = "worker-capi.yaml"
#         cp_capi_file_name = "controlplane-capi.yaml"
#         ctx.run(
#             "talosctl machineconfig patch worker.yaml --patch @worker-patches.yaml -o {}".format(
#                 worker_capi_file_name
#             ),
#             echo=True
#         )
#         ctx.run(
#             "talosctl machineconfig patch controlplane.yaml --patch @controlplane-patches.yaml -o {}".format(
#                 cp_capi_file_name
#             ),
#             echo=True
#         )
#
#         add_talos_hashbang(os.path.join(cluster_secrets_dir, worker_capi_file_name))
#         add_talos_hashbang(os.path.join(cluster_secrets_dir, cp_capi_file_name))
#
#         ctx.run("talosctl validate -m cloud -c {}".format(worker_capi_file_name))
#         ctx.run("talosctl validate -m cloud -c {}".format(cp_capi_file_name))
#
#     with open(cluster_manifest_file_name) as cluster_manifest_file:
#         documents = list()
#         for document in yaml.safe_load_all(cluster_manifest_file):
#             if document['kind'] == 'TalosControlPlane':
#                 del (document['spec']['controlPlaneConfig']['controlplane']['configPatches'])
#                 document['spec']['controlPlaneConfig']['controlplane']['generateType'] = "none"
#                 with open(os.path.join(cluster_secrets_dir, cp_capi_file_name), 'r') as talos_cp_config_file:
#                     document['spec']['controlPlaneConfig']['controlplane']['data'] = talos_cp_config_file.read()
#
#             if document['kind'] == 'TalosConfigTemplate':
#                 del (document['spec']['template']['spec']['configPatches'])
#                 document['spec']['template']['spec']['generateType'] = 'none'
#                 with open(os.path.join(cluster_secrets_dir, worker_capi_file_name), 'r') as talos_worker_config_file:
#                     document['spec']['template']['spec']['data'] = talos_worker_config_file.read()
#
#             documents.append(document)
#
#     with open(cluster_manifest_static_file_name, 'w') as static_manifest:
#         # yaml.safe_dump_all(documents, static_manifest, sort_keys=True)
#         # ToDo: pyyaml for some reason when used with safe_dump_all dumps the inner multiline string as
#         # single line long string
#         # spec:
#         #   template:
#         #     spec:
#         #       data: "#!talos\ncluster:\n  ca:\n
#         #
#         # instead of a multiline string
#         yaml.dump_all(documents, static_manifest, sort_keys=True)


# @task(talosctl_gen_config)
# def talos_apply_config_patches(ctx):
#     """
#     Produces [secrets_dir]/[cluster_name]/((controlplane)|(worker))-capi.yaml
#     as a talos cli compatible configuration files, to be used in benchmark deployment.
#     Validate configuration files with talosctl validate
#     Prepend #!talos as per
#     https://www.talos.dev/v1.3/talos-guides/install/bare-metal-platforms/equinix-metal/#passing-in-the-configuration-as-user-data
#     """
#     for cluster_spec in get_constellation_clusters():
#         _talos_apply_config_patch(ctx, cluster_spec)


@task()
def get_cluster_secrets(ctx, talosconfig='talosconfig', cluster_name=None):
    """
    Produces [secrets_dir]/[cluster_name].kubeconfig
    """
    # ToDo: kubectl create secret generic --from-file ~/.gocy/jupiter/jupiter/talosconfig jupiter-talosconfig
    if cluster_name is None:
        print("Can't continue without a cluster name, check {} for available options.".format(
            get_secrets_dir()
        ))
        return

    device_list_file_name = os.path.join(
        get_secrets_dir(),
        "device-list.yaml"
    )

    ctx.run("metal device get -o yaml > {}".format(device_list_file_name))
    ip_addresses = dict()
    role_control_plane = 'control-plane'
    role_worker = 'worker'
    with open(device_list_file_name, 'r') as device_list_file:
        for element in yaml.safe_load(device_list_file):
            if cluster_name in element['hostname']:
                for ip_address in element['ip_addresses']:
                    if ip_address['address_family'] == 4 and ip_address['public'] is True:
                        if role_control_plane in element['hostname']:
                            ip_addresses[ip_address['address']] = role_control_plane
                        else:
                            ip_addresses[ip_address['address']] = role_worker

    if len(ip_addresses) == 0:
        print("No devices found for cluster {}, setup failed.".format(cluster_name))
        return

    cluster_config_dir = os.path.join(get_secrets_dir(), cluster_name)
    with open(os.path.join(cluster_config_dir, talosconfig), 'r') as talos_config_file:
        talos_config_data = yaml.safe_load(talos_config_file)
        talos_config_data['contexts'][cluster_name]['nodes'] = list()
        talos_config_data['contexts'][cluster_name]['endpoints'] = list()

    control_plane_node = None
    for key in ip_addresses:
        talos_config_data['contexts'][cluster_name]['nodes'].append(key)

        if ip_addresses[key] == role_control_plane:
            talos_config_data['contexts'][cluster_name]['endpoints'].append(key)
            control_plane_node = key

    talosconfig_path = os.path.join(cluster_config_dir, talosconfig)
    with open(talosconfig_path, 'w') as talos_config_file:
        yaml.dump(talos_config_data, talos_config_file)

    ctx.run("talosctl config merge " + talosconfig_path, echo=True)

    kubeconfig_path = os.path.join(cluster_config_dir, cluster_name + ".kubeconfig")
    if control_plane_node is None:
        print('Could not produce ' + kubeconfig_path)
        return

    ctx.run("talosctl --talosconfig {} bootstrap --nodes {} | true".format(
        talosconfig_path,
        control_plane_node), echo=True)

    ctx.run("talosctl --talosconfig {} --nodes {} kubeconfig {}".format(
        talosconfig_path,
        get_cp_vip_address(get_cluster_spec(ctx, cluster_name)),
        kubeconfig_path
    ), echo=True)

    """
    With current deployment method - TalosControlPlane throws an error:
    {"namespace": "argo-infra", "talosControlPlane": "saturn-control-plane", "error": "Secret \"saturn-talosconfig\" not found"}
    The following is a workaround:
    """
    ctx.run('kubectl --namespace {} create secret generic {}-talosconfig --from-file="{}"'.format(
        get_argo_infra_namespace_name(),
        cluster_name,
        talosconfig_path
    ), echo=True)

    ctx.run("kconf add " + kubeconfig_path, echo=True, pty=True)
    ctx.run("kconf use admin@" + cluster_name, echo=True, pty=True)


def clean_constellation_dir():
    files_to_remove = glob.glob(
        os.path.join(
            get_secrets_dir(),
            '**'),
        recursive=True)
    files_to_remove = list(map(lambda fname: re.sub("/$", "", fname), files_to_remove))

    whitelisted_files = [
        get_secrets_dir(),
        os.path.join(get_secrets_dir(), 'secrets')
    ]
    whitelisted_files = list(map(lambda fname: re.sub("/$", "", fname), whitelisted_files))

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


def create(ctx, cluster_name: str = None):
    """
    Applies initial cluster manifest - the management cluster(CAPI) on local kind cluster.
    """
    state = SystemContext()
    project_paths = ProjectPaths(state.constellation.name)

    ctx.run("kubectl apply -f {}".format(
        project_paths.cluster_capi_static_manifest_file()), echo=True)


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
