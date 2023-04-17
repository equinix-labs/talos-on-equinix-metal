import glob
import os
import shutil

import yaml
from invoke import task

from tasks_pkg.equinix_metal import register_cp_vip, generate_cpem_config, register_vips
from tasks_pkg.helpers import str_presenter, get_cluster_name, get_secrets_dir, \
    get_cpem_config_yaml, get_cp_vip_address
from tasks_pkg.k8s_context import use_kind_cluster_context
from tasks_pkg.network import build_network_service_dependencies_manifest

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


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


@task(register_cp_vip, use_kind_cluster_context)
def clusterctl_generate_cluster(ctx, templates_dir='templates', cluster_template_name=None):
    """
    Produces ClusterAPI manifest, to be applied on the management cluster.
    """
    if cluster_template_name is None:
        cluster_template_name = get_cluster_name() + '.yaml'

    ctx.run("clusterctl generate cluster {} \
    --from {} > {}".format(
        get_cluster_name(),
        os.path.join(templates_dir, cluster_template_name),
        os.path.join(get_secrets_dir(), get_cluster_name() + ".yaml")
    ),
        echo=True,
        env={
            'TOEM_CPEM_SECRET': get_cpem_config_yaml(),
            'TOEM_CP_ENDPOINT': get_cp_vip_address()
        }
    )


@task(register_cp_vip)
def talosctl_gen_config(ctx):
    """
    Produces initial Talos machine configuration, that later on will be patched with custom cluster settings.
    """
    with ctx.cd(get_secrets_dir()):
        ctx.run(
            "talosctl gen config {} https://{}:6443".format(
                get_cluster_name(),
                get_cp_vip_address()
            ),
            echo=True
        )


def add_talos_hashbang(filename):
    with open(filename, 'r') as file:
        data = file.read()

    with open(filename, 'w') as file:
        file.write("#!talos\n" + data)


@task(talosctl_gen_config)
def talos_apply_config_patches(ctx):
    """
    Generate (controlplane)|(worker)-capi.yaml as a talos cli compatible configuration files,
    to be used in benchmark deployment.
    Validate configuration files with talosctl validate
    Prepend #!talos as per
    https://www.talos.dev/v1.3/talos-guides/install/bare-metal-platforms/equinix-metal/#passing-in-the-configuration-as-user-data
    """
    with open(os.path.join(get_secrets_dir(), get_cluster_name() + '.yaml')) as cluster_manifest_file:
        for document in yaml.safe_load_all(cluster_manifest_file):
            if document['kind'] == 'TalosControlPlane':
                with open(os.path.join(get_secrets_dir(), 'controlplane-patches.yaml'), 'w') as cp_patches_file:
                    yaml.dump(
                        document['spec']['controlPlaneConfig']['controlplane']['configPatches'],
                        cp_patches_file
                    )
            if document['kind'] == 'TalosConfigTemplate':
                with open(os.path.join(get_secrets_dir(), 'worker-patches.yaml'), 'w') as worker_patches_file:
                    yaml.dump(
                        document['spec']['template']['spec']['configPatches'],
                        worker_patches_file
                    )

    with ctx.cd(get_secrets_dir()):
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

        add_talos_hashbang(os.path.join(get_secrets_dir(), worker_capi_file_name))
        add_talos_hashbang(os.path.join(get_secrets_dir(), cp_capi_file_name))

        ctx.run("talosctl validate -m cloud -c {}".format(worker_capi_file_name))
        ctx.run("talosctl validate -m cloud -c {}".format(cp_capi_file_name))

    with open(os.path.join(get_secrets_dir(), get_cluster_name() + '.yaml')) as cluster_manifest_file:
        documents = list()
        for document in yaml.safe_load_all(cluster_manifest_file):
            if document['kind'] == 'TalosControlPlane':
                del (document['spec']['controlPlaneConfig']['controlplane']['configPatches'])
                document['spec']['controlPlaneConfig']['controlplane']['generateType'] = "none"
                with open(os.path.join(get_secrets_dir(), cp_capi_file_name), 'r') as talos_cp_config_file:
                    document['spec']['controlPlaneConfig']['controlplane']['data'] = talos_cp_config_file.read()

            if document['kind'] == 'TalosConfigTemplate':
                del (document['spec']['template']['spec']['configPatches'])
                document['spec']['template']['spec']['generateType'] = 'none'
                with open(os.path.join(get_secrets_dir(), worker_capi_file_name), 'r') as talos_worker_config_file:
                    document['spec']['template']['spec']['data'] = talos_worker_config_file.read().strip()

            documents.append(document)

    with open(os.path.join(get_secrets_dir(), get_cluster_name() + ".static-config.yaml"), 'w') as static_manifest:
        yaml.safe_dump_all(documents, static_manifest, sort_keys=True)


@task(use_kind_cluster_context)
def get_cluster_secrets(ctx, talosconfig='talosconfig'):
    """
    produces: [secrets_dir]/[cluster_name].kubeconfig
    """
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
            if get_cluster_name() in element['hostname']:
                for ip_address in element['ip_addresses']:
                    if ip_address['address_family'] == 4 and ip_address['public'] == True:
                        if role_control_plane in element['hostname']:
                            ip_addresses[ip_address['address']] = role_control_plane
                        else:
                            ip_addresses[ip_address['address']] = role_worker

    if len(ip_addresses) == 0:
        print("No devices found for cluster {}, setup failed.".format(get_cluster_name()))
        return

    with open(os.path.join(get_secrets_dir(), talosconfig), 'r') as talos_config_file:
        talos_config_data = yaml.safe_load(talos_config_file)
        talos_config_data['contexts'][get_cluster_name()]['nodes'] = list()
        talos_config_data['contexts'][get_cluster_name()]['endpoints'] = list()

    control_plane_node = None
    for key in ip_addresses:
        talos_config_data['contexts'][get_cluster_name()]['nodes'].append(key)

        if ip_addresses[key] == role_control_plane:
            talos_config_data['contexts'][get_cluster_name()]['endpoints'].append(key)
            control_plane_node = key

    with open(os.path.join(get_secrets_dir(), talosconfig), 'w') as talos_config_file:
        yaml.dump(talos_config_data, talos_config_file)

    if control_plane_node is None:
        print('Could not produce ' + os.path.join(get_secrets_dir(), get_cluster_name() + ".kubeconfig"))
        return

    ctx.run("talosctl --talosconfig {} bootstrap --nodes {}".format(
        os.path.join(get_secrets_dir(), talosconfig),
        control_plane_node), echo=True)

    ctx.run("talosctl --talosconfig {} --nodes {} kubeconfig {}".format(
        os.path.join(get_secrets_dir(), talosconfig),
        get_cp_vip_address(),
        os.path.join(get_secrets_dir(), get_cluster_name() + ".kubeconfig")
    ), echo=True)


@task()
def kind_clusterctl_init(ctx):
    """
    Produces local management(kind) k8s cluster and inits it with ClusterAPI
    """
    ctx.run("kind create cluster --name {}".format(os.environ.get('CAPI_KIND_CLUSTER_NAME')), echo=True)
    ctx.run("clusterctl init -b talos -c talos -i packet", echo=True)


@task()
def clean(ctx):
    """
    USE WITH CAUTION! - Nukes all local configuration.
    """
    secret_files = glob.glob(
        os.path.join(
            ctx.core.secrets_dir,
            '**'),
        recursive=True)

    whitelisted_files = [
        ctx.core.secrets_dir,
        os.path.join(ctx.core.secrets_dir, 'metal')
    ]

    files_to_remove = list(set(secret_files) - set(whitelisted_files))
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
                print("{} already gone".format(name))


@task(clean, use_kind_cluster_context, generate_cpem_config, register_vips, patch_template_with_cilium_manifest,
      clusterctl_generate_cluster, talos_apply_config_patches)
def build_manifests_inline_cni(ctx):
    """
    Produces cluster manifests with inline CNI - cilium
    """


@task()
def produce_cluster_template(ctx):
    with ctx.cd("templates"):
        ctx.run("cp default.yaml " + get_cluster_name() + ".yaml")


@task(clean, use_kind_cluster_context, generate_cpem_config, register_vips, produce_cluster_template,
      clusterctl_generate_cluster, talos_apply_config_patches)
def build_manifests(ctx):
    """
    Produces cluster manifests
    """
