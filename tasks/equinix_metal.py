import glob
import json
import os

import ipcalc
import yaml
from invoke import task

from tasks.helpers import str_presenter, get_secrets_dir, \
    get_cpem_config, get_cfg, get_constellation_spec

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task()
def generate_cpem_config(ctx, cpem_config_file_name="cpem/cpem.yaml"):
    """
    Produces [secrets_dir]/cpem/cpem.yaml - 'Cloud Provider for Equinix Metal' config spec
    """
    cpem_config = get_cpem_config()
    ctx.run("mkdir -p {}".format(
        os.path.join(
            get_secrets_dir(),
            'cpem'
        )
    ), echo=True)

    command = "kubectl create -o yaml \
    --dry-run='client' secret generic -n kube-system metal-cloud-config \
    --from-literal='cloud-sa.json={}'"

    print("In background ran something similar to: \n{}".format(command))
    k8s_secret = ctx.run(command.format(
        json.dumps(cpem_config)
    ), hide='stdout', echo=False)

    yaml_k8s_secret = yaml.safe_load(k8s_secret.stdout)
    del yaml_k8s_secret['metadata']['creationTimestamp']

    with open(os.path.join(get_secrets_dir(), cpem_config_file_name), 'w') as cpem_config_file:
        yaml.dump(yaml_k8s_secret, cpem_config_file)


@task()
def create_config_dirs(ctx):
    """
    Produces [secrets_dir]/[cluster_name...] config directories based of spec defined in invoke.yaml
    """
    cluster_spec = get_constellation_spec(ctx)
    for cluster in cluster_spec:
        ctx.run("mkdir -p {}".format(os.path.join(
            get_secrets_dir(),
            cluster['name']
        )), echo=True)


@task()
def get_project_ips(ctx, project_ips_file_name=None):
    """
    Produces [secrets_dir]/project-ips.yaml with IP addressed used in the current Equinix Metal project.
    """

    project_ips_file_name = get_cfg(project_ips_file_name, ctx.equinix_metal.project_ips_file_name)
    ctx.run("metal ip get -o yaml > {}".format(project_ips_file_name), echo=True)


def _render_ip_addresses_file(ip_reservation, addresses, ip_addresses_file_name):
    for address in ipcalc.Network('{}/{}'.format(ip_reservation['address'], ip_reservation['cidr'])):
        addresses.append(str(address))
    with open(ip_addresses_file_name, 'w') as ip_addresses_file:
        yaml.dump(addresses, ip_addresses_file)


def render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name):
    addresses = list()
    with open(ip_reservations_file_name, 'r') as ip_reservations_file:
        _render_ip_addresses_file(yaml.safe_load(ip_reservations_file), addresses, ip_addresses_file_name)


def get_ip_addresses_file_name(cluster_spec, address_role):
    return os.path.join(
        get_secrets_dir(),
        cluster_spec['name'],
        "ip-{}-addresses.yaml".format(address_role)
    )


def get_ip_reservation_file_name(cluster_spec, address_role):
    return os.path.join(
        get_secrets_dir(),
        cluster_spec['name'],
        "ip-{}-reservation.yaml".format(address_role)
    )


def register_global_vip(ctx, cluster_spec, cp_tags, ip_reservations_file_name):
    """
    We want to ensure that only one global_ipv4 is registered for all satellites. Following behaviour should not
    affect the management cluster (bary).
    """
    if cluster_spec['name'] != ctx.constellation.bary.name:
        existing_ip_reservation_file_names = glob.glob(
            os.path.join(
                ctx.core.secrets_dir,
                '**',
                os.path.basename(ip_reservations_file_name)
            ),
            recursive=True)
        for existing_ip_reservation_file_name in existing_ip_reservation_file_names:
            if ctx.constellation.bary.name not in existing_ip_reservation_file_name:
                if cluster_spec['name'] not in existing_ip_reservation_file_name:
                    print('Global IP reservation file already exists. Copying config for satellite: '
                          + cluster_spec['name'])
                    ctx.run('cp {} {}'.format(
                        existing_ip_reservation_file_name,
                        ip_reservations_file_name
                    ), echo=True)
                    return

    # Todo: There is a bug in Metal CLI that prevents us from using the CLI in this case.
    #       Thankfully API endpoint works.
    #       https://deploy.equinix.com/developers/docs/metal/networking/global-anycast-ips/
    payload = {
        "type": "global_ipv4",
        "quantity": 1,
        "fail_on_approval_required": "false",
        "tags": cp_tags
    }
    ctx.run("curl -s -X POST "
            "-H 'Content-Type: application/json' "
            "-H \"X-Auth-Token: {}\" "
            "\"https://api.equinix.com/metal/v1/projects/{}/ips\" "
            "-d '{}' | yq e -P - > {}".format(
                "${METAL_AUTH_TOKEN}",
                "${METAL_PROJECT_ID}",
                json.dumps(payload),
                ip_reservations_file_name
            ), echo=True)


def register_vip(ctx, cluster_spec, project_ips_file_name, address_role, address_type, address_count):
    cluster_facility = cluster_spec['facility']

    ip_reservations_file_name = get_ip_reservation_file_name(cluster_spec, address_role)
    ip_addresses_file_name = get_ip_addresses_file_name(cluster_spec, address_role)
    # ToDo: Most likely, despite all the efforts to disable it
    #   https://github.com/kubernetes-sigs/cluster-api-provider-packet registers a VIP
    #   We need one so we will use it...
    if address_role == 'cp':
        cp_tags = ["cluster-api-provider-packet:cluster-id:{}".format(cluster_spec['name'])]
    else:
        cp_tags = ["gocy:vip:{}".format(address_role), "gocy:cluster:{}".format(cluster_spec['name'])]

    if os.path.isfile(ip_reservations_file_name):
        render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name)
        return

    with open(project_ips_file_name, 'r') as all_ips_file:
        no_reservations = False
        addresses = list()
        # ToDo: OMG FIX or DELETE ME!
        for ip_spec in yaml.safe_load(all_ips_file):
            if (ip_spec['global_ip'] or ('facility' in ip_spec and ip_spec['facility']['code'] == cluster_facility))\
                    and 'tags' in ip_spec and len(ip_spec.get('tags')) > 0 and ip_spec.get('tags')[0] == cp_tags[0]:
                _render_ip_addresses_file(ip_spec, addresses, ip_addresses_file_name)
                no_reservations = False
                break
            else:
                no_reservations = True

        if no_reservations:
            if address_type == 'public_ipv4':
                ctx.run("metal ip request -p {} -t {} -q {} -f {} --tags '{}' -o yaml > {}".format(
                    "${METAL_PROJECT_ID}",
                    address_type,
                    address_count,
                    cluster_facility,
                    ",".join(cp_tags),
                    ip_reservations_file_name
                ), echo=True)
            elif address_type == 'global_ipv4':
                register_global_vip(ctx, cluster_spec, cp_tags, ip_reservations_file_name)
            else:
                print("Unsupported address_type: " + address_type)

            render_ip_addresses_file(ip_reservations_file_name, ip_addresses_file_name)


@task(get_project_ips, create_config_dirs)
def register_vips(ctx, project_ips_file_name=None):
    """
    Registers VIPs as per constellation spec in invoke.yaml
    """
    project_ips_file_name = get_cfg(project_ips_file_name, ctx.equinix_metal.project_ips_file_name)
    constellation_spec = get_constellation_spec(ctx)
    for cluster_spec in constellation_spec:
        for vip in cluster_spec['vips']:
            register_vip(ctx, cluster_spec, project_ips_file_name, vip['role'], vip['type'], vip['count'])


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

