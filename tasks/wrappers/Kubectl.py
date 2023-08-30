import base64
import json
import logging

import yaml
from invoke import Context, Failure

from tasks.dao.SystemContext import SystemContext
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace


class SimplePod:
    name: str
    node: str
    gateway: str

    def __init__(self, name, node):
        self.name = name
        self.node = node


class Kubectl:

    _ctx: Context
    _state: SystemContext
    _echo: bool

    def __init__(self, ctx: Context, state: SystemContext, echo: bool):
        self._ctx = ctx
        self._state = state
        self._echo = echo

    def get_pods(self, namespace: Namespace) -> dict:
        pods = self._ctx.run(
            "kubectl -n {} get pods -o yaml".format(namespace.value),
            hide='stdout', echo=self._echo).stdout

        return dict(yaml.safe_load(pods))['items']

    def get_pods_name_and_node(self, namespace: Namespace, pod_name: str) -> dict[str, SimplePod]:
        """
        returns dict Hostname: SimplePod; with SimplePod.gateway being the most important thing here
        """
        pods = self.get_pods(namespace)
        result = dict()
        for pod in pods:
            if pod_name in pod['metadata']['name']:
                result[pod['spec']['nodeName']] = SimplePod(pod['metadata']['name'], pod['spec']['nodeName'])
        return result

    def get_nodes(self) -> dict:
        nodes = self._ctx.run(
            "kubectl get nodes -o yaml",
            hide='stdout', echo=self._echo).stdout

        return dict(yaml.safe_load(nodes))

    def get_nodes_eip(self) -> dict[str, list]:
        """
        Returns dict Hostname: [ExternalIP, ...]
        """
        nodes = self.get_nodes()
        hostname_vs_eip = dict()
        for item in nodes['items']:
            hostname = None
            eip = list()
            for address in item['status']['addresses']:
                if address['type'] == 'Hostname':
                    hostname = address['address']
                if address['type'] == 'ExternalIP':
                    eip.append(address['address'])

            if hostname is not None and eip is not None:
                hostname_vs_eip[hostname] = eip

        return hostname_vs_eip

    def configure_image_pull_secrets(self, namespace: Namespace):
        """
        Det up the docker pull secret on the default Service Account in a given namespace.
        """
        d_user = self._state.secrets['env']['DOCKERHUB_USER']
        d_pass = self._state.secrets['env']['DOCKERHUB_TOKEN']
        auth_bytes = "{}:{}".format(d_user, d_pass).encode('utf-8')
        docker_config = {
            "auths": {
                'https://hub.docker.com': {
                    'auth': base64.b64encode(auth_bytes).decode('utf-8')
                }
            }
        }

        docker_config_file_name = self._state.project_paths.docker_config_file()
        with open(docker_config_file_name, 'w') as docker_config_file:
            json.dump(docker_config, docker_config_file)

        secret_name = "dockerhub"
        self._ctx.run(
            "kubectl -n {} create secret docker-registry --from-file=.dockerconfigjson=\"{}\" {} | true".format(
                namespace,
                docker_config_file_name,
                secret_name
            ), echo=self._echo)

        payload = {
            'imagePullSecrets': [
                {
                    "name": secret_name
                }
            ]
        }
        self._ctx.run("kubectl patch sa default -n {} -p '{}' | true".format(
            namespace,
            json.dumps(payload)
        ), echo=self._echo)

    def create_tls_secret(self, name: str, namespace: Namespace, crt_path: str, key_path: str):
        try:
            self._ctx.run("kubectl --namespace {} create secret tls {} --cert={} --key={}".format(
                namespace,
                name,
                crt_path,
                key_path
            ), echo=self._echo)
        except Failure:
            logging.info("Apparently secret {} already exists in namespace {}".format(namespace, name))

    def get_cluster_status(self, namespace: Namespace):
        # kubectl get machinedeployments.cluster.x-k8s.io,taloscontrolplanes.controlplane.cluster.x-k8s.io -n argocd -o yaml
        # kubectl -n argocd get clusters
        pass

    def cilium_annotate(self, cluster: Cluster, namespace: Namespace, service_name: str):
        self._ctx.run(
            "kubectl --context admin@{} --namespace {} annotate service {} "
            "'io.cilium/global-service'='true' ".format(
                cluster.name,
                namespace.value,
                service_name
            ), echo=self._echo)
        self._ctx.run(
            "kubectl --context admin@{} --namespace {} annotate service {} "
            "'service.cilium.io/affinity'='local'".format(
                cluster.name,
                namespace.value,
                service_name
            ), echo=self._echo)
