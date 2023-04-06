import json
import os

import yaml
from invoke import task

from tasks_pkg.helpers import str_presenter, get_secrets_dir, get_cluster_name

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dum


@task
def hack_fix_bgp_peer_routs(ctx, talosconfig_file_name='talosconfig', namespace='network-services'):
    with open(os.path.join(get_secrets_dir(), talosconfig_file_name), 'r') as talosconfig_file:
        talosconfig = yaml.safe_load(talosconfig_file)

    hack_directory = os.path.join('hack', 'bgp')
    with ctx.cd(hack_directory):
        ctx.run("kubectl apply -f manifest.yaml", echo=True)
        pods_raw = ctx.run(
            "kubectl -n {} get pods -o yaml".format(namespace),
            hide='stdout', echo=True).stdout

        debug_pods = list()
        for pod in yaml.safe_load(pods_raw)['items']:
            if 'debug' in pod['metadata']['name']:
                debug_pods.append({
                    "name": pod['metadata']['name'],
                    'node': pod['spec']['nodeName']
                })

        for debug_pod in debug_pods:
            if 'debug' in debug_pod['name']:
                debug_pod['gateway'] = ctx.run("kubectl -n network-services exec {} -- /bin/bash "
                                               "-c \"curl -s https://metadata.platformequinix.com/metadata | "
                                               "jq -r '.network.addresses[] | "
                                               "select(.public == false and .address_family == 4) | .gateway'\"".format(
                    debug_pod['name'])
                    , echo=True
                ).stdout.strip()

        node_patch_data = dict()
        for pod in debug_pods:
            node_patch_data[pod['node']] = dict()
            node_patch_data[pod['node']]['gateway'] = pod['gateway']

        nodes_raw = ctx.run("kubectl get nodes -o yaml", hide='stdout', echo=True).stdout
        for node in yaml.safe_load(nodes_raw)['items']:
            node_patch_data[node['metadata']['labels']['kubernetes.io/hostname']]['addresses'] = list()
            node_patch_data[node['metadata']['labels']['kubernetes.io/hostname']]['addresses'] = node['status']['addresses']

        # print("#### node_patch_data")
        # print(node_patch_data)
        # print("#### talosconfig")
        # print(talosconfig)

        if len(node_patch_data.keys()) != len(talosconfig['contexts'][get_cluster_name()]['nodes']):
            print("Node list returned by kubectl is out of sync with your talosconfig! Fix before patching.")
            return

        for hostname in node_patch_data:
            patch_name = "{}.json".format(hostname)
            talos_patch = None
            if 'control-plane' in hostname:
                with open(os.path.join(
                        hack_directory,
                        'talos-control-plane-patch.template.yaml'), 'r') as talos_cp_patch_file:
                    talos_patch = yaml.safe_load(talos_cp_patch_file)
                    for route in talos_patch[0]['value']['routes']:
                        route['gateway'] = node_patch_data[hostname]['gateway']
            elif 'worker' in hostname:
                with open(os.path.join(
                        hack_directory,
                        'talos-worker-patch.template.yaml'), 'r') as talos_cp_patch_file:
                    talos_patch = yaml.safe_load(talos_cp_patch_file)
                    for route in talos_patch[1]['value']['routes']:
                        route['gateway'] = node_patch_data[hostname]['gateway']
            else:
                print('Unrecognised node role: {}, should be "control-plane" OR "worker. '
                      'Node will NOT be patched.'.format(hostname))

            if talos_patch is not None:
                patch_file_name = os.path.join(hack_directory, patch_name)
                with open(patch_file_name, 'w') as patch_file:
                    json.dump(talos_patch, patch_file, indent=2)

                for address in node_patch_data[hostname]['addresses']:
                    if address['type'] == 'ExternalIP' and address['address'] in talosconfig['contexts'][get_cluster_name()]['nodes']:
                        ctx.run("talosctl --talosconfig {} patch mc --nodes {} --patch @{}".format(
                            os.path.join(
                                os.environ.get('TOEM_PROJECT_ROOT'),
                                get_secrets_dir(),
                                talosconfig_file_name),
                            address['address'],
                            patch_name
                        ), echo=True)


@task()
def install_network_service_dependencies(ctx):
    chart_directory = os.path.join('apps', 'network-services-dependencies')
    with ctx.cd(chart_directory):
        ctx.run("helm dependencies update", echo=True)
        ctx.run("kubectl apply -f namespace.yaml", echo=True)
        ctx.run("helm upgrade --install --namespace network-services network-services-dependencies ./", echo=True)


@task(install_network_service_dependencies, hack_fix_bgp_peer_routs)
def install_network_services(ctx):
    chart_directory = os.path.join('apps', 'network-services')
    with ctx.cd(chart_directory):
        ctx.run("helm dependencies update", echo=True)
        ctx.run("helm upgrade --install --namespace network-services network-services ./", echo=True)