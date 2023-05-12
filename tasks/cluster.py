import glob
import os
import re
import shutil

import yaml
from invoke import task

from tasks.constellation_v01 import Cluster
from tasks.equinix_metal import generate_cpem_config, register_vips
from tasks.helpers import str_presenter, get_cluster_name, get_secrets_dir, \
    get_cpem_config_yaml, get_cp_vip_address, get_constellation_clusters, get_cluster_spec, \
    get_cluster_spec_from_context, get_constellation
from tasks.k8s_context import use_kind_cluster_context, use_bary_cluster_context
from tasks.network import build_network_service_dependencies_manifest

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump

_CLUSTER_MANIFEST_FILE_NAME = "cluster-manifest.yaml"
_CLUSTER_MANIFEST_STATIC_FILE_NAME = "cluster-manifest.static-config.yaml"


@task(build_network_service_dependencies_manifest)
def patch_template_with_cilium_manifest(
        ctx,
        templates_dir='templates',
        cluster_template_file_name='inline-cni.yaml',
        manifest_name='network-services-dependencies.yaml'):
    """
    Patch talos machine config with cilium CNI manifest for inline installation method
    https://www.talos.dev/v1.3/kubernetes-guides/network/deploying-cilium/#method-4-helm-manifests-inline-install
    """

    with open(os.path.join(get_secrets_dir(), manifest_name), 'r') as network_manifest_file:
        network_manifest = list(yaml.safe_load_all(network_manifest_file))

    network_manifest_yaml = yaml.safe_dump_all(network_manifest)
    with open(os.path.join(templates_dir, cluster_template_file_name), 'r') as cluster_template_file:
        _cluster_template = list(yaml.safe_load_all(cluster_template_file))
        for document in _cluster_template:
            if document['kind'] == 'TalosControlPlane':
                for patch in document['spec']['controlPlaneConfig']['controlplane']['configPatches']:
                    if 'name' in patch['value'] and patch['value']['name'] == 'network-services-dependencies':
                        patch['value']['contents'] = network_manifest_yaml
            if document['kind'] == 'TalosConfigTemplate':
                for patch in document['spec']['template']['spec']['configPatches']:
                    if 'name' in patch['value'] and patch['value']['name'] == 'network-services-dependencies':
                        patch['value']['contents'] = network_manifest_yaml

        with open(os.path.join(templates_dir, get_cluster_name() + '.yaml'), 'w') as target:
            yaml.safe_dump_all(_cluster_template, target)


def patch_cluster_spec_network(cluster_spec: Cluster, cluster_template: list):
    """
    Patches cluster template with corrected dnsDomain,podSubnets,serviceSubnets
    As a result of a bug? settings in Cluster.spec.clusterNetwork do not affect the running cluster.
    Those changes need to be put in the Talos config.
    """
    for document in cluster_template:
        if document['kind'] == 'TalosControlPlane':
            patches = document['spec']['controlPlaneConfig']['controlplane']['configPatches']
            for patch in patches:
                if patch['path'] == '/cluster/network':
                    patch['value']['dnsDomain'] = "{}.local".format(cluster_spec.name)
                    patch['value']['podSubnets'] = cluster_spec.pod_cidr_blocks
                    patch['value']['serviceSubnets'] = cluster_spec.service_cidr_blocks
        if document['kind'] == 'TalosConfigTemplate':
            patches = document['spec']['template']['spec']['configPatches']
            for patch in patches:
                if patch['path'] == '/cluster/network':
                    patch['value']['dnsDomain'] = "{}.local".format(cluster_spec.name)
                    patch['value']['podSubnets'] = cluster_spec.pod_cidr_blocks
                    patch['value']['serviceSubnets'] = cluster_spec.service_cidr_blocks
        if document['kind'] == 'Cluster':
            document['spec']['clusterNetwork']['pods']['cidrBlocks'] = cluster_spec.pod_cidr_blocks
            document['spec']['clusterNetwork']['services']['cidrBlocks'] = cluster_spec.service_cidr_blocks

    return cluster_template


def patch_cluster_spec_machine_pools(cluster_spec: Cluster, cluster_template: list):
    for document in cluster_template:
        if document['kind'] == 'MachineDeployment':
            machine_deployment = document['kind']

    return cluster_template


@task(register_vips, use_kind_cluster_context)
def generate_cluster_spec(ctx, dev_mode=False,
                          cluster_spec_template_file_name='cluster_spec_template.yaml',
                          cluster_spec_file_name='cluster_spec.yaml'):
    """
    Produces ClusterAPI manifest - ~/.gocy/[Constellation_name][Cluster_name]/cluster_spec.yaml
    In this particular case we are dealing with two kind of config specifications. Cluster API one
    and Talos Linux one. As per official CAPI documentation https://cluster-api.sigs.k8s.io/tasks/using-kustomize.html,
    this functionality is currently limited. As of now Kustomize alone can not produce satisfactory result.
    This is why we go with some custom python + jinja template solution.
    """
    for cluster in get_constellation_clusters():
        with open(os.path.join('templates', cluster_spec_template_file_name), 'r') as cluster_spec_template_file:
            cluster_spec = list(yaml.safe_load_all(cluster_spec_template_file))

            cluster_spec = patch_cluster_spec_network(cluster, cluster_spec)
        # ctx.run("clusterctl generate cluster {} --from {} > {}".format(
        #     cluster_spec.name,
        #     os.path.join(get_secrets_dir(), cluster_spec.name, cluster_spec_template_file_name),
        #     os.path.join(get_secrets_dir(), cluster_spec.name, _CLUSTER_MANIFEST_FILE_NAME)
        # ),
        #     echo=True,
        #     env={
        #         'TOEM_CPEM_SECRET': get_cpem_config_yaml(),
        #         'TOEM_CP_ENDPOINT': get_cp_vip_address(cluster_spec),
        #         'SERVICE_DOMAIN': "{}.local".format(cluster_spec.name),
        #         'CLUSTER_NAME': cluster_spec.name,
        #         'METRO': cluster_spec.metro
        #     }
        # )
        with open(os.path.join(
                get_secrets_dir(), cluster.name, cluster_spec_file_name), 'w') as cluster_template_file:
            yaml.safe_dump_all(cluster_spec, cluster_template_file)


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


def add_talos_hashbang(filename):
    with open(filename, 'r') as file:
        data = file.read()

    with open(filename, 'w') as file:
        file.write("#!talos\n" + data)


def _talos_apply_config_patch(ctx, cluster_spec):
    cluster_manifest_file_name = os.path.join(get_secrets_dir(), cluster_spec.name, _CLUSTER_MANIFEST_FILE_NAME)
    cluster_manifest_static_file_name = os.path.join(
        get_secrets_dir(), cluster_spec.name, _CLUSTER_MANIFEST_STATIC_FILE_NAME)
    config_dir_name = os.path.join(get_secrets_dir(), cluster_spec.name)

    with open(cluster_manifest_file_name) as cluster_manifest_file:
        for document in yaml.safe_load_all(cluster_manifest_file):
            if document['kind'] == 'TalosControlPlane':
                with open(os.path.join(config_dir_name, 'controlplane-patches.yaml'), 'w') as cp_patches_file:
                    yaml.dump(
                        document['spec']['controlPlaneConfig']['controlplane']['configPatches'],
                        cp_patches_file
                    )
            if document['kind'] == 'TalosConfigTemplate':
                with open(os.path.join(config_dir_name, 'worker-patches.yaml'), 'w') as worker_patches_file:
                    yaml.dump(
                        document['spec']['template']['spec']['configPatches'],
                        worker_patches_file
                    )

    with ctx.cd(config_dir_name):
        worker_capi_file_name = "worker-capi.yaml"
        cp_capi_file_name = "controlplane-capi.yaml"
        ctx.run(
            "talosctl machineconfig patch worker.yaml --patch @worker-patches.yaml -o {}".format(
                worker_capi_file_name
            ),
            echo=True
        )
        ctx.run(
            "talosctl machineconfig patch controlplane.yaml --patch @controlplane-patches.yaml -o {}".format(
                cp_capi_file_name
            ),
            echo=True
        )

        add_talos_hashbang(os.path.join(config_dir_name, worker_capi_file_name))
        add_talos_hashbang(os.path.join(config_dir_name, cp_capi_file_name))

        ctx.run("talosctl validate -m cloud -c {}".format(worker_capi_file_name))
        ctx.run("talosctl validate -m cloud -c {}".format(cp_capi_file_name))

    with open(cluster_manifest_file_name) as cluster_manifest_file:
        documents = list()
        for document in yaml.safe_load_all(cluster_manifest_file):
            if document['kind'] == 'TalosControlPlane':
                del (document['spec']['controlPlaneConfig']['controlplane']['configPatches'])
                document['spec']['controlPlaneConfig']['controlplane']['generateType'] = "none"
                with open(os.path.join(config_dir_name, cp_capi_file_name), 'r') as talos_cp_config_file:
                    document['spec']['controlPlaneConfig']['controlplane']['data'] = talos_cp_config_file.read()

            if document['kind'] == 'TalosConfigTemplate':
                del (document['spec']['template']['spec']['configPatches'])
                document['spec']['template']['spec']['generateType'] = 'none'
                with open(os.path.join(config_dir_name, worker_capi_file_name), 'r') as talos_worker_config_file:
                    document['spec']['template']['spec']['data'] = talos_worker_config_file.read().strip()

            documents.append(document)

    with open(cluster_manifest_static_file_name, 'w') as static_manifest:
        yaml.safe_dump_all(documents, static_manifest, sort_keys=True)


@task(talosctl_gen_config)
def talos_apply_config_patches(ctx):
    """
    Produces [secrets_dir]/[cluster_name]/((controlplane)|(worker))-capi.yaml
    as a talos cli compatible configuration files, to be used in benchmark deployment.
    Validate configuration files with talosctl validate
    Prepend #!talos as per
    https://www.talos.dev/v1.3/talos-guides/install/bare-metal-platforms/equinix-metal/#passing-in-the-configuration-as-user-data
    """
    for cluster_spec in get_constellation_clusters():
        _talos_apply_config_patch(ctx, cluster_spec)


@task(use_kind_cluster_context)
def get_cluster_secrets(ctx, talosconfig='talosconfig', cluster_name=None):
    """
    Produces [secrets_dir]/[cluster_name].kubeconfig
    """
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

    with open(os.path.join(cluster_config_dir, talosconfig), 'w') as talos_config_file:
        yaml.dump(talos_config_data, talos_config_file)

    if control_plane_node is None:
        print('Could not produce ' + os.path.join(cluster_config_dir, cluster_name + ".kubeconfig"))
        return

    ctx.run("talosctl --talosconfig {} bootstrap --nodes {} | true".format(
        os.path.join(cluster_config_dir, talosconfig),
        control_plane_node), echo=True)

    ctx.run("talosctl --talosconfig {} --nodes {} kubeconfig {}".format(
        os.path.join(cluster_config_dir, talosconfig),
        get_cp_vip_address(get_cluster_spec(ctx, cluster_name)),
        os.path.join(cluster_config_dir, cluster_name + ".kubeconfig")
    ), echo=True)


@task()
def clusterctl_init(ctx):
    """
    Runs clusterctl init with our favourite provider set.
    """
    constellation = get_constellation()
    cluster_spec = get_cluster_spec_from_context(ctx)
    if cluster_spec is not None and cluster_spec.name == constellation.bary.name:
        user_input = input('Is cert-manager present ? '
                           '- did you run "invoke apps.install-dns-and-tls-dependencies" [y/N] ?')
        if user_input.strip().lower() != 'y':
            return

    ctx.run("clusterctl init "
            "--core=cluster-api:{} "
            "--bootstrap=talos:{} "
            "--control-plane=talos:{} "
            "--infrastructure=packet:{}".format(
                    constellation.capi,
                    constellation.cabpt,
                    constellation.cacppt,
                    constellation.capp
                ), echo=True)


@task(post=[clusterctl_init])
def kind_clusterctl_init(ctx, name='toem-capi-local'):
    """
    Produces local management(kind) k8s cluster and inits it with ClusterAPI
    """
    ctx.run("kind create cluster --name {}".format(name), echo=True)


@task()
def clean(ctx):
    """
    USE WITH CAUTION! - Nukes all local configuration.
    """
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

    user_input = input('Continue y/N ?')
    if user_input.strip().lower() == 'y':
        for name in files_to_remove:
            try:
                if os.path.isfile(name):
                    os.remove(name)
                else:
                    shutil.rmtree(name)
            except OSError:
                pass


# ToDo: Fix or remove ?
# @task(clean, use_kind_cluster_context, generate_cpem_config, register_vips, patch_template_with_cilium_manifest,
#       clusterctl_generate_cluster, talos_apply_config_patches)
# def build_manifests_inline_cni(ctx):
#     """
#     Produces cluster manifests with inline CNI - cilium
#     """


@task(clean, use_kind_cluster_context, generate_cpem_config, register_vips,
      generate_cluster_spec, talos_apply_config_patches)
def build_manifests(ctx):
    """
    Produces cluster manifests
    """


@task(use_kind_cluster_context)
def apply_bary_manifest(ctx, cluster_manifest_static_file_name=_CLUSTER_MANIFEST_STATIC_FILE_NAME):
    """
    Applies initial cluster manifest - the management cluster(CAPI) on local kind cluster.
    """
    constellation = get_constellation()
    ctx.run("kubectl apply -f {}".format(
        os.path.join(
            get_secrets_dir(),
            constellation.bary.name,
            cluster_manifest_static_file_name
        )
    ), echo=True)


@task()
def clusterctl_move(ctx):
    """
    Move CAPI objects from local kind cluster to the management(bary) cluster
    """
    use_bary_cluster_context(ctx)
    clusterctl_init(ctx)
    use_kind_cluster_context(ctx)

    constellation = get_constellation()
    bary_kubeconfig = os.path.join(
        get_secrets_dir(), constellation.bary.name, constellation.bary.name + '.kubeconfig')
    ctx.run("clusterctl move --to-kubeconfig=" + bary_kubeconfig, echo=True)
