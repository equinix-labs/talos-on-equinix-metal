import json
import os

import ipcalc
import yaml
from invoke import task

from tasks_pkg.helpers import str_presenter, get_cluster_name, get_secrets_dir, \
    get_cpem_config

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


@task(get_all_metal_ips)
def register_ingress_vip(
        ctx, all_ips_file_name=None, address_role="ingress", address_count=1, address_scope="global_ipv4"):
    """
    Register VIP (VirtualIP) 'global ipv4' to be used for anycast ingress
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
    nodes = dict()
    bary_facility = ctx.constellation.bary.facility
    nodes[bary_facility] = dict()
    bary_roles = ctx.constellation.bary.nodes.keys()
    for role in bary_roles:
        for node in ctx.constellation.bary.nodes[role]:
            node_type = node['type']
            if node_type not in nodes[bary_facility]:
                nodes[bary_facility][node_type] = node['count']
            else:
                nodes[bary_facility][node_type] = nodes[bary_facility][node_type] + node['count']

    for satellite in ctx.constellation.satellites:
        satellite_facility = satellite['facility']
        if satellite_facility not in nodes:
            nodes[satellite_facility] = dict()

        satellite_roles = satellite['nodes'].keys()
        for role in satellite_roles:
            for node in satellite['nodes'][role]:
                satellite_type = node['type']
                if satellite_type not in nodes[satellite_facility]:
                    nodes[satellite_facility][satellite_type] = node['count']
                else:
                    nodes[satellite_facility][satellite_type] = nodes[satellite_facility][satellite_type] + node['count']

    for facility in nodes:
        for node_type, count in nodes[facility].items():
            ctx.run("metal capacity check -f {} -P {} -q {}".format(
                facility, node_type, count
            ), echo=True)


