import os

import yaml
from invoke import task

from tasks_pkg.helpers import str_presenter, get_secrets_dir, get_cp_vip_address, \
    get_cluster_spec_from_context, get_constellation_spec

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dum


@task()
def deploy_network_multitool(ctx):
    """
    Deploys Network-multitool DaemonSet to enable BGP fix and debugging
    """
    chart_directory = os.path.join('apps', 'network-multitool')
    with ctx.cd(chart_directory):
        ctx.run("helm upgrade --install --wait --namespace network-services network-multitool ./", echo=True)


@task(deploy_network_multitool)
def hack_fix_bgp_peer_routs(ctx, talosconfig_file_name='talosconfig', namespace='network-services'):
    """
    Adds a static route to the node configuration, so that BGP peers could connect.
    Something like https://github.com/kubernetes-sigs/cluster-api-provider-packet/blob/main/templates/cluster-template-kube-vip.yaml#L195
    """
    cluster_spec = get_cluster_spec_from_context(ctx)
    cluster_cfg_dir = os.path.join(ctx.core.secrets_dir, cluster_spec['name'])

    with open(os.path.join(cluster_cfg_dir, talosconfig_file_name), 'r') as talosconfig_file:
        talosconfig = yaml.safe_load(talosconfig_file)

    templates_directory = os.path.join('patch-templates', 'bgp')
    patches_directory = os.path.join(ctx.core.secrets_dir, 'patch', 'bgp')
    ctx.run("mkdir -p " + patches_directory, echo=True)

    with ctx.cd(templates_directory):
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
        if len(debug_pods) == 0:
            print("This task requires debug pods from 'network.deploy-network-multitool' "
                  "something went wrong, exiting.")
            return

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
        node_patch_addresses = list()
        for node in yaml.safe_load(nodes_raw)['items']:
            node_addresses = node['status']['addresses']
            node_addresses = list(filter(lambda address: address['type'] == 'ExternalIP', node_addresses))
            node_addresses = list(map(lambda address: address['address'], node_addresses))
            node_patch_data[
                node['metadata']['labels']['kubernetes.io/hostname']]['addresses'] = node_addresses
            node_patch_addresses.extend(node_addresses)

        # print("#### node_patch_data")
        # pprint(node_patch_addresses)
        # print("#### talosconfig")
        # pprint(talosconfig['contexts'][cluster_spec['name']]['nodes'])

        if len(set(node_patch_addresses) - set(talosconfig['contexts'][cluster_spec['name']]['nodes'])) > 0:
            print("Node list returned by kubectl is out of sync with your talosconfig! Fix before patching.")
            return

        for hostname in node_patch_data:
            patch_name = "{}.yaml".format(hostname)
            talos_patch = None
            if 'control-plane' in hostname:
                with open(os.path.join(
                        templates_directory,
                        'control-plane.pt.yaml'), 'r') as talos_cp_patch_file:
                    talos_patch = yaml.safe_load(talos_cp_patch_file)
                    for route in talos_patch[0]['value']['routes']:
                        route['gateway'] = node_patch_data[hostname]['gateway']
            elif 'worker' in hostname:
                with open(os.path.join(
                        templates_directory,
                        'worker.pt.yaml'), 'r') as talos_cp_patch_file:
                    talos_patch = yaml.safe_load(talos_cp_patch_file)
                    for route in talos_patch[1]['value']['routes']:
                        route['gateway'] = node_patch_data[hostname]['gateway']
            else:
                print('Unrecognised node role: {}, should be "control-plane" OR "worker. '
                      'Node will NOT be patched.'.format(hostname))

            if talos_patch is not None:
                patch_file_name = os.path.join(patches_directory, patch_name)
                with open(patch_file_name, 'w') as patch_file:
                    yaml.safe_dump(talos_patch, patch_file)

                for address in node_patch_data[hostname]['addresses']:
                    ctx.run("talosctl --talosconfig {} patch mc --nodes {} --patch @{}".format(
                        os.path.join(
                            os.environ.get('TOEM_PROJECT_ROOT'),
                            cluster_cfg_dir,
                            talosconfig_file_name),
                        address,
                        patch_file_name
                    ), echo=True)


@task()
def build_network_service_dependencies_manifest(ctx, manifest_name='network-services-dependencies'):
    """
    Produces [secrets_dir]/network-services-dependencies.yaml - Helm cilium manifest to be used
    as inlineManifest is Talos machine specification (Helm manifests inline install).
    https://www.talos.dev/v1.4/kubernetes-guides/network/deploying-cilium/#method-4-helm-manifests-inline-install
    """
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
    cluster_spec = get_cluster_spec_from_context(ctx)
    constellation_spec = get_constellation_spec(ctx)

    cluster_id = 0
    for index, value in enumerate(constellation_spec):
        if value == cluster_spec:
            cluster_id = index

    with ctx.cd(chart_directory):
        ctx.run("helm dependencies update", echo=True)
        ctx.run("kubectl apply -f namespace.yaml")
        ctx.run("helm upgrade --install "
                "--set cilium.k8sServiceHost={} "
                "--set cilium.k8sServicePort={} "
                "--set cilium.cluster.name={} "
                "--set cilium.cluster.id={} "
                "--namespace network-services network-services-dependencies ./".format(
                    get_cp_vip_address(get_cluster_spec_from_context(ctx)),
                    '6443',
                    cluster_spec['name'],
                    cluster_id
                ),
                echo=True)


@task(hack_fix_bgp_peer_routs)
def install_network_services(ctx):
    cluster_spec = get_cluster_spec_from_context(ctx)
    
    chart_directory = os.path.join('apps', 'network-services')
    with ctx.cd(chart_directory):
        ctx.run("helm dependencies update", echo=True)
        ctx.run("helm upgrade --install --namespace network-services network-services ./", echo=True)
