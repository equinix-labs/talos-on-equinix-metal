import os

import ipcalc
from invoke import task, Collection
import glob
import yaml


@task(help={'name': "Name of the person to say hi to."})
def hi(ctx, name=None):
    """
    Say hi to someone.
    """
    if name is None:
        name = ctx.build.name
    print("yo! {}!".format(name))


@task()
def get_all_metal_ips(ctx, all_ips_file=None):
    """
    Gets IP addresses for the Equinix Metal Project
    """
    if all_ips_file is None:
        all_ips_file = ctx.core.all_ips_file_name

    ctx.run("metal ip get -o yaml > {}".format(all_ips_file), echo=True)


def _render_ip_addresses_file(document, addresses, ip_addresses_file_name):
    for address in ipcalc.Network('{}/{}'.format(document['address'], document['cidr'])):
        addresses.append(str(address))
    with open(ip_addresses_file_name, 'w') as ip_addresses_file:
        ip_addresses_file.write(yaml.dump(addresses))


def render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name):
    addresses = list()
    with open(ip_reservations_file_name, 'r') as ip_reservations_file:
        for document in yaml.safe_load_all(ip_reservations_file):
            _render_ip_addresses_file(document, addresses, ip_addresses_file_name)


def register_vip(ctx, all_ips_file_name, address_role, address_count, address_scope):
    ip_reservations_file_name = "secrets/ip-{}-reservation.yaml".format(address_role)
    ip_addresses_file_name = "secrets/ip-{}-addresses.yaml".format(address_role)
    cp_tags = ["talos-{}-vip".format(address_role), "cluster:{}".format(os.environ.get('CLUSTER_NAME'))]

    if os.path.isfile(ip_reservations_file_name):
        render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name)
        return

    with open(all_ips_file_name, 'r') as all_ips_file:
        no_reservations = False
        addresses = list()
        for document in yaml.unsafe_load_all(all_ips_file):
            for element in document:
                if element['facility']['code'] == os.environ.get('FACILITY') and element.get('tags') == cp_tags:
                    _render_ip_addresses_file(element, addresses, ip_addresses_file_name)
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
def clean(ctx):
    secret_files = glob.glob('./secrets/**', recursive=True)
    whitelisted_files = [
        './secrets/',
        './secrets/metal'
    ]

    files_to_remove = list(set(secret_files) - set(whitelisted_files))
    for name in files_to_remove:
        os.remove(name)


ns = Collection(
    hi,
    get_all_metal_ips,
    register_cp_vip,
    register_ingress_vip,
    register_vpn_vip,
    register_vips,
    clean
)
# Maps to INVOKE_BUILD_NAME
ns.configure({
    'hi': {'name': 'kali2'},
    'core': {
        'all_ips_file_name': 'secrets/all-ips.yaml'
    }
})

