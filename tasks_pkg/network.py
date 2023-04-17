import json
import os

import yaml
from invoke import task

from tasks_pkg.helpers import str_presenter, get_secrets_dir, get_cluster_name, get_cp_vip_address

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dum


@task()
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
                debug_pod['gateway'] = ctx.run(
                    "kubectl -n {} exec {} -- /bin/bash "
                    "-c \"curl -s https://metadata.platformequinix.com/metadata | "
                    "jq -r '.network.addresses[] | "
                    "select(.public == false and .address_family == 4) | .gateway'\"".format(
                        namespace,
                        debug_pod['name'])
                    , echo=True).stdout.strip()

        node_patch_data = dict()
        for pod in debug_pods:
            node_patch_data[pod['node']] = dict()
            node_patch_data[pod['node']]['gateway'] = pod['gateway']

        nodes_raw = ctx.run("kubectl get nodes -o yaml", hide='stdout', echo=True).stdout
        for node in yaml.safe_load(nodes_raw)['items']:
            node_patch_data[node['metadata']['labels']['kubernetes.io/hostname']]['addresses'] = list()
            node_patch_data[node['metadata']['labels']['kubernetes.io/hostname']]['addresses'] = node['status'][
                'addresses']

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
                    if address['type'] == 'ExternalIP' and address['address'] in \
                            talosconfig['contexts'][get_cluster_name()]['nodes']:
                        ctx.run("talosctl --talosconfig {} patch mc --nodes {} --patch @{}".format(
                            os.path.join(
                                os.environ.get('TOEM_PROJECT_ROOT'),
                                get_secrets_dir(),
                                talosconfig_file_name),
                            address['address'],
                            patch_name
                        ), echo=True)


@task()
def build_network_service_dependencies_manifest(ctx, manifest_name='network-services-dependencies'):
    chart_directory = os.path.join('apps', manifest_name)
    manifest_file_name = os.path.join(
        get_secrets_dir(),
        manifest_name + '.yaml')
    with ctx.cd(chart_directory):
        ctx.run("helm dependencies update", echo=True)
        ctx.run("helm template --namespace network-services "
                "--set cilium.bpf.masquerade=true "
                "--set cilium.kubeProxyReplacement=strict "
                "--set cilium.k8sServiceHost={} "
                "--set cilium.k8sServicePort={} "
                " {} ./ > {}".format(
                    get_cp_vip_address(),
                    '6443',
                    manifest_name,
                    manifest_file_name
                ), echo=True)

    # Talos controller chokes on the '\n' in yaml
    # [talos] controller failed {
    #       "component": "controller-runtime",
    #       "controller": "k8s.ExtraManifestController",
    #       "error": "1 error occurred:\x5cn\x5ct* error updating manifests:
    #           invalid Yaml document separator: null\x5cn\x5cn"
    #   }
    # Helm does not mind those, we need to fix them.
    manifest = list()
    with open(manifest_file_name, 'r') as manifest_file:
        _manifest = list(yaml.safe_load_all(manifest_file))

        for document in _manifest:
            if document is not None:
                if 'data' in document:
                    data_keys = document['data'].keys()
                    for key in data_keys:
                        if '\n' in document['data'][key]:
                            tmp_list = document['data'][key].split('\n')
                            for index, _ in enumerate(tmp_list):
                                tmp_list[index] = tmp_list[index].rstrip()
                            document['data'][key] = "\n".join(tmp_list).strip()
                manifest.append(document)

    with open(manifest_file_name, 'w') as manifest_file:
        yaml.safe_dump_all(manifest, manifest_file)


@task()
def install_network_service_dependencies(ctx):
    chart_directory = os.path.join('apps', 'network-services-dependencies')
    with ctx.cd(chart_directory):
        ctx.run("helm dependencies update", echo=True)
        ctx.run("kubectl apply -f namespace.yaml")
        ctx.run("helm upgrade --install "
                "--set cilium.k8sServiceHost={} "
                "--set cilium.k8sServicePort={} "
                "--namespace network-services network-services-dependencies ./".format(
                    get_cp_vip_address(),
                    '6443',
                ),
                echo=True)


@task(hack_fix_bgp_peer_routs)
def install_network_services(ctx):
    chart_directory = os.path.join('apps', 'network-services')
    with ctx.cd(chart_directory):
        ctx.run("helm dependencies update", echo=True)
        ctx.run("helm upgrade --install --namespace network-services network-services ./", echo=True)