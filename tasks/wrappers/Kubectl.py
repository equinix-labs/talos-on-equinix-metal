import yaml
from invoke import Context

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
    _echo: bool

    def __init__(self, ctx: Context, echo: bool):
        self._ctx = ctx
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
