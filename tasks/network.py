import base64
import json
import os

import yaml
from invoke import task

from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter, get_secrets_dir, get_cp_vip_address, \
    get_cluster_spec_from_context
from tasks.models.Namespaces import Namespace

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


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

    docker_config_file_name = os.path.join(get_secrets_dir(), "docker.config.json")
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
        cluster_spec.name
    ), echo=True)


# @task(deploy_network_multitool, post=[apply_kubespan_patch])
@task(deploy_network_multitool)
def hack_fix_bgp_peer_routs(ctx, talosconfig_file_name='talosconfig', namespace='network-services'):
    """
    Adds a static route to the node configuration, so that BGP peers could connect.
    Something like https://github.com/kubernetes-sigs/cluster-api-provider-packet/blob/main/templates/cluster-template-kube-vip.yaml#L195
    """
    cluster_spec = get_cluster_spec_from_context(ctx)
    cluster_cfg_dir = os.path.join(get_secrets_dir(), cluster_spec.name)

    with open(os.path.join(cluster_cfg_dir, talosconfig_file_name), 'r') as talosconfig_file:
        talosconfig = yaml.safe_load(talosconfig_file)

    templates_directory = os.path.join('patch-templates', 'bgp')
    patches_directory = os.path.join(get_secrets_dir(), 'patch', 'bgp')
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

        talosconfig_addresses = talosconfig['contexts'][cluster_spec.name]['nodes']
        try:
            talosconfig_addresses.remove(cp_vip)
        except ValueError:
            pass

        # from pprint import pprint
        # print("#### node_patch_data")
        # pprint(node_patch_addresses)
        # print("#### talosconfig")
        # pprint(talosconfig_addresses)
        # return

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
            elif 'machine' in hostname:
                with open(os.path.join(
                        templates_directory,
                        'worker.pt.yaml'), 'r') as talos_cp_patch_file:
                    talos_patch = yaml.safe_load(talos_cp_patch_file)
                    for route in talos_patch[1]['value']['routes']:
                        route['gateway'] = node_patch_data[hostname]['gateway']
            else:
                print('Unrecognised node role: {}, should be "control-plane" OR "machine. '
                      'Node will NOT be patched.'.format(hostname))

            if talos_patch is not None:
                patch_file_name = os.path.join(patches_directory, patch_name)
                with open(patch_file_name, 'w') as patch_file:
                    yaml.safe_dump(talos_patch, patch_file)

                for address in node_patch_data[hostname]['addresses']:
                    ctx.run("talosctl --talosconfig {} patch mc --nodes {} --patch @{}".format(
                        os.path.join(
                            os.environ.get('GOCY_DEFAULT_ROOT'),
                            cluster_cfg_dir,
                            talosconfig_file_name),
                        address,
                        patch_file_name
                    ), echo=True)


@task()
def enable_cluster_mesh(ctx, echo: bool = False):
    """
    Enables Cilium ClusterMesh
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    state = SystemContext(ctx, echo)
    state.set_bary_cluster()

    constellation = state.constellation
    for cluster in state.constellation:
        if cluster.name != constellation.bary.name:
            ctx.run("cilium --namespace {} --context {} clustermesh connect --destination-context {}".format(
                Namespace.network_services,
                'admin@' + constellation.bary.name,
                'admin@' + cluster.name
            ), echo=True)
        else:
            print("Switch k8s context to {} and try again".format(constellation.bary.name))
