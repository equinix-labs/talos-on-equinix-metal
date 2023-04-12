import glob
import json
import os
import shutil

import ipcalc
import yaml
from invoke import task, Collection

from tasks_pkg import apps, network
from tasks_pkg.helpers import str_presenter, get_cluster_name, get_secrets_dir, \
    get_cpem_config_yaml, get_cp_vip_address, get_cpem_config
from tasks_pkg.network import build_network_service_dependencies_manifest

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task()
def generate_cpem_config(ctx, cpem_config_file="secrets/cpem/cpem.yaml"):
    """
    Generates config for 'Cloud Provider for Equinix Metal'
    {}
    """.format(cpem_config_file)
    cpem_config = get_cpem_config()
    ctx.run("mkdir -p secrets/cpem", echo=True)
    k8s_secret = ctx.run("kubectl create -o yaml \
    --dry-run='client' secret generic -n kube-system metal-cloud-config \
    --from-literal='cloud-sa.json={}'".format(
        json.dumps(cpem_config)
    ), hide='stdout', echo=True)

    # print(k8s_secret.stdout)
    yaml_k8s_secret = yaml.safe_load(k8s_secret.stdout)
    del yaml_k8s_secret['metadata']['creationTimestamp']

    with open(cpem_config_file, 'w') as cpem_config:
        yaml.dump(yaml_k8s_secret, cpem_config)


@task()
def get_all_metal_ips(ctx, all_ips_file=None):
    """
    Gets IP addresses for the Equinix Metal Project
    Produces {}
    """.format(all_ips_file)
    if all_ips_file is None:
        all_ips_file = ctx.core.all_ips_file_name

    ctx.run("metal ip get -o yaml > {}".format(all_ips_file), echo=True)


def _render_ip_addresses_file(document, addresses, ip_addresses_file_name):
    for address in ipcalc.Network('{}/{}'.format(document['address'], document['cidr'])):
        addresses.append(str(address))
    with open(ip_addresses_file_name, 'w') as ip_addresses_file:
        yaml.dump(addresses, ip_addresses_file)


def render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name):
    addresses = list()
    with open(ip_reservations_file_name, 'r') as ip_reservations_file:
        for document in yaml.safe_load(ip_reservations_file):
            _render_ip_addresses_file(document, addresses, ip_addresses_file_name)


def get_ip_addresses_file_name(address_role):
    return os.path.join(
        get_secrets_dir(),
        "ip-{}-addresses.yaml".format(address_role)
    )


def get_ip_reservation_file_name(address_role):
    return os.path.join(
        get_secrets_dir(),
        "ip-{}-reservation.yaml".format(address_role)
    )


def register_vip(ctx, all_ips_file_name, address_role, address_count, address_scope):
    ip_reservations_file_name = get_ip_reservation_file_name(address_role)
    ip_addresses_file_name = get_ip_addresses_file_name(address_role)
    if address_role == 'cp':
        cp_tags = ["cluster-api-provider-packet:cluster-id:{}".format(get_cluster_name())]
    else:
        cp_tags = ["talos-{}-vip".format(address_role), "cluster:{}".format(os.environ.get('CLUSTER_NAME'))]

    if os.path.isfile(ip_reservations_file_name):
        render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name)
        return

    with open(all_ips_file_name, 'r') as all_ips_file:
        no_reservations = False
        addresses = list()
        for ip_spec in yaml.safe_load(all_ips_file):
            if ip_spec['facility']['code'] == os.environ.get('FACILITY') and ip_spec.get('tags') == cp_tags:
                _render_ip_addresses_file(ip_spec, addresses, ip_addresses_file_name)
                no_reservations = False
                break
            else:
                no_reservations = True

        if no_reservations:
            ctx.run("metal ip request -p {} -t {} -q {} -f {} --tags '{}' -o yaml > {}".format(
                os.environ.get('METAL_PROJECT_ID'),
                address_scope,
                address_count,
                os.environ.get('FACILITY'),
                ",".join(cp_tags),
                ip_reservations_file_name
            ), echo=True)

            render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name)


@task(get_all_metal_ips)
def register_vpn_vip(ctx, all_ips_file_name=None, address_role="vpn", address_count=2, address_scope="public_ipv4"):
    """
    Registers a VIP to be used for anycast ingress
    """
    if all_ips_file_name is None:
        all_ips_file_name = ctx.core.all_ips_file_name

    register_vip(ctx, all_ips_file_name, address_role, address_count, address_scope)


# ToDo: Registering a global_ipv4 is broken
@task(get_all_metal_ips)
def register_ingress_vip(
        ctx, all_ips_file_name=None, address_role="ingress", address_count=1, address_scope="public_ipv4"):
    """
    Registers a VIP 'global ipv4' to be used for anycast ingress
    Be patient, registering one takes a human intervention on the Equinix Metal side.
    """
    if all_ips_file_name is None:
        all_ips_file_name = ctx.core.all_ips_file_name

    register_vip(ctx, all_ips_file_name, address_role, address_count, address_scope)


@task(get_all_metal_ips)
def register_cp_vip(ctx, all_ips_file_name=None, address_role="cp", address_count=1, address_scope="public_ipv4"):
    """
    Registers a VIP to be managed by Talos, used as Control Plane endpoint
    """
    if all_ips_file_name is None:
        all_ips_file_name = ctx.core.all_ips_file_name

    register_vip(ctx, all_ips_file_name, address_role, address_count, address_scope)


@task(register_vpn_vip, register_ingress_vip, register_cp_vip)
def register_vips(ctx):
    """
    Registers VIPs required by the setup.
    """


@task()
def use_kind_cluster_context(ctx, kind_cluster_name="kind-toem-capi-local"):
    ctx.run("kconf use {}".format(kind_cluster_name), echo=True)


@task(build_network_service_dependencies_manifest)
def patch_template_with_cilium_manifest(
        ctx,
        templates_dir='templates',
        cluster_template_file_name='inline-cni.yaml',
        manifest_name='network-services-dependencies.yaml'):

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
    Generate cluster spec with clusterctl
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

    with open(os.path.join(get_secrets_dir(), talosconfig), 'r') as talosconfig_file:
        talosconfig_data = yaml.safe_load(talosconfig_file)
        talosconfig_data['contexts'][get_cluster_name()]['nodes'] = list()
        talosconfig_data['contexts'][get_cluster_name()]['endpoints'] = list()

    for key in ip_addresses:
        talosconfig_data['contexts'][get_cluster_name()]['nodes'].append(key)

        if ip_addresses[key] == role_control_plane:
            talosconfig_data['contexts'][get_cluster_name()]['endpoints'].append(key)
            control_plane_node = key

    with open(os.path.join(get_secrets_dir(), talosconfig), 'w') as talosconfig_file:
        yaml.dump(talosconfig_data, talosconfig_file)

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
    ctx.run("kind create cluster --name {}".format(os.environ.get('CAPI_KIND_CLUSTER_NAME')), echo=True)
    ctx.run("clusterctl init -b talos -c talos -i packet", echo=True)


@task()
def clean(ctx):
    secret_files = glob.glob('./secrets/**', recursive=True)
    whitelisted_files = [
        './secrets/',
        './secrets/metal'
    ]

    files_to_remove = list(set(secret_files) - set(whitelisted_files))
    for name in files_to_remove:
        try:
            if os.path.isfile(name):
                os.remove(name)
            else:
                shutil.rmtree(name)
        except:
            print("{} already gone".format(name))


@task(clean, use_kind_cluster_context, generate_cpem_config, register_vips, patch_template_with_cilium_manifest,
      clusterctl_generate_cluster, talos_apply_config_patches)
def build_manifests_inline_cni(ctx):
    """
    Build all
    """


@task()
def produce_cluster_template(ctx):
    with ctx.cd("templates"):
        ctx.run("cp kubeproxy.yaml " + get_cluster_name() + ".yaml")


@task(clean, use_kind_cluster_context, generate_cpem_config, register_vips, produce_cluster_template,
      clusterctl_generate_cluster, talos_apply_config_patches)
def build_manifests_kubeproxy(ctx):
    """
    Build all
    """


ns = Collection()
ns.add_task(patch_template_with_cilium_manifest)
ns.add_task(kind_clusterctl_init)
ns.add_task(build_manifests_kubeproxy)
ns.add_task(build_manifests_inline_cni)
ns.add_task(clusterctl_generate_cluster)
ns.add_task(generate_cpem_config)
ns.add_task(get_all_metal_ips)
ns.add_task(register_cp_vip)
ns.add_task(register_ingress_vip)
ns.add_task(register_vpn_vip)
ns.add_task(register_vips)
ns.add_task(talosctl_gen_config)
ns.add_task(talos_apply_config_patches)
ns.add_task(use_kind_cluster_context)
ns.add_task(get_cluster_secrets)
ns.add_task(clean)

ns.add_collection(network)
ns.add_collection(apps)

ns.configure({
    'tasks': {
        'search_root': os.environ.get('TOEM_PROJECT_ROOT')
    },
    'core': {
        'all_ips_file_name': 'secrets/all-ips.yaml'
    }
})
