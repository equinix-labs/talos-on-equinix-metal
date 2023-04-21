import base64
import json
import os

import yaml
from invoke import task

from tasks_pkg.apps import install_ingress_controller
from tasks_pkg.helpers import str_presenter, get_secrets_dir, get_cp_vip_address, \
    get_cluster_spec_from_context, get_constellation_spec, get_vips

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dum


@task()
def setup_dockerhub_pull_secret(ctx, namespace="network-services"):
    """
    Network-multitool container image is stored in docker hub. It might happen that it won't deploy due to
    `You have reached your pull rate limit. You may increase the limit by authenticating and upgrading: https://www.docker.com/increase-rate-limit`
    This task sets up the docker pull secret on the default Service Account in a given namespace.
    """
    auth_bytes = "{}:{}".format(os.environ.get('DOCKERHUB_USER'), os.environ.get('DOCKERHUB_TOKEN')).encode('utf-8')
    docker_config = {
        "auths": {
            'https://registry-1.docker.io': {
                'auth': base64.b64encode(auth_bytes).decode('utf-8')
            }
        }
    }

    docker_config_file_name = os.path.join(ctx.core.secrets_dir, "docker.config.json")
    with open(docker_config_file_name, 'w') as docker_config_file:
        json.dump(docker_config, docker_config_file)

    secret_name = "dockerhub"
    ctx.run("kubectl -n {} create secret docker-registry --from-file=.dockerconfigjson=\"{}\" {} | true".format(
        namespace,
        docker_config_file_name,
        secret_name
    ), echo=True)

    payload = {
        'imagePullSecrets': [
            {
                "name": secret_name
            }
        ]
    }
    ctx.run("kubectl patch sa default -n {} -p '{}' | true".format(
        namespace,
        json.dumps(payload)
    ), echo=True)


@task(setup_dockerhub_pull_secret)
def deploy_network_multitool(ctx, namespace="network-services"):
    """
    Deploys Network-multitool DaemonSet to enable BGP fix and debugging
    """
    chart_directory = os.path.join('apps', 'network-multitool')
    with ctx.cd(chart_directory):
        ctx.run("helm upgrade --install --wait --namespace {} network-multitool ./".format(
            namespace
        ), echo=True)


@task()
def apply_kubespan_patch(ctx):
    """
    For some reason, Kubespan turns off once cilium is deployed.
    https://www.talos.dev/v1.4/kubernetes-guides/network/kubespan/
    Once the patch is applied kubespan is back up.
    """
    cluster_spec = get_cluster_spec_from_context(ctx)
    ctx.run("talosctl --context {} patch mc -p @patch-templates/kubespan/common.pt.yaml".format(
        cluster_spec['name']
    ), echo=True)


@task(deploy_network_multitool, post=[apply_kubespan_patch])
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

        cp_vip = get_cp_vip_address(cluster_spec)
        try:
            node_patch_addresses.remove(cp_vip)
        except ValueError:
            pass

        talosconfig_addresses = talosconfig['contexts'][cluster_spec['name']]['nodes']
        try:
            talosconfig_addresses.remove(cp_vip)
        except ValueError:
            pass

        # from pprint import pprint
        # print("#### node_patch_data")
        # pprint(node_patch_addresses)
        # print("#### talosconfig")
        # pprint(talosconfig_addresses)

        if len(set(node_patch_addresses) - set(talosconfig_addresses)) > 0:
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


@task(post=[apply_kubespan_patch])
def install_network_service_dependencies(ctx):
    """
    Deploy chart apps/network-services-dependencies containing Cilium and MetalLB
    """
    chart_directory = os.path.join('apps', 'network-services-dependencies')
    cluster_spec = get_cluster_spec_from_context(ctx)
    constellation_spec = get_constellation_spec(ctx)

    # We have to count form one
    # Error: Unable to connect cluster:
    #   local cluster has the default name (cluster name: jupiter) and/or ID 0 (cluster ID: 0)
    cluster_id = 1
    for index, value in enumerate(constellation_spec):
        if value == cluster_spec:
            cluster_id = cluster_id + index

    # ToDo: If bary cluster is up, thus this runs on a worker cluster, copy its cilium-ca and pass it to the chart:
    # {{- $crt := .Values.tls.ca.cert -}}
    # {{- $key := .Values.tls.ca.key -}}
    # https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#shared-certificate-authority
    # kubectl --context admin@jupiter -n network-services get secret cilium-ca -o yaml

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
def install_network_service(ctx):
    """
    Deploys apps/network-services chart, with BGP VIP pool configuration, based on
    VIPs registered in EquinixMetal. As of now the assumption is 1 GlobalIPv4 for ingress,
    1 PublicIPv4 for Cilium Mesh API server.
    """
    cluster_spec = get_cluster_spec_from_context(ctx)
    cluster_cfg_dir = os.path.join(ctx.core.secrets_dir, cluster_spec['name'])
    mesh_vips = get_vips(cluster_spec, 'mesh')
    ingress_vips = get_vips(cluster_spec, 'ingress')
    chart_directory = os.path.join('apps', 'network-services')
    with open(os.path.join(chart_directory, 'values.template.yaml'), 'r') as value_template_file:
        chart_values = dict(yaml.safe_load(value_template_file))
        chart_values['metallb']['clusterName'] = cluster_spec['name']
        chart_values['metallb']['pools'] = list()
        chart_values['metallb']['pools'].append({
            'name': 'mesh',
            'addresses': ["{}/32".format(mesh_vips[0])]
        })
        chart_values['metallb']['pools'].append({
            'name': 'ingress',
            'addresses': ["{}/32".format(ingress_vips[0])]
        })

    network_services_values_file_name = os.path.join(
        os.environ.get('TOEM_PROJECT_ROOT'),
        cluster_cfg_dir,
        'values.network-services.yaml')
    with open(network_services_values_file_name, 'w') as value_template_file:
        yaml.safe_dump(chart_values, value_template_file)

    with ctx.cd(chart_directory):
        ctx.run("helm upgrade --install --values {} --namespace network-services network-services ./".format(
            network_services_values_file_name
        ), echo=True)


@task()
def enable_cluster_mesh(ctx, namespace='network-services'):
    """
    Enables Cilium ClusterMesh
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    for cluster_spec in get_constellation_spec(ctx):
        ctx.run("cilium --namespace {} --context {} clustermesh enable --service-type LoadBalancer".format(
            namespace,
            "admin@" + cluster_spec['name']
        ), echo=True)

    for cluster_spec in get_constellation_spec(ctx):
        if cluster_spec['name'] != ctx.constellation.bary.name:
            ctx.run("cilium --namespace {} --context {} clustermesh connect --destination-context {}".format(
                namespace,
                'admin@' + ctx.constellation.bary.name,
                'admin@' + cluster_spec['name']
            ), echo=True)
