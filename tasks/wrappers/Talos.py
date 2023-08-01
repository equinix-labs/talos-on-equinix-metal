import yaml
from invoke import Context

from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.models.ConstellationSpecV01 import Cluster


class Talos:

    _ctx: Context
    _paths: ProjectPaths
    _cluster: Cluster
    _echo: bool

    def __init__(self, ctx: Context, state: SystemContext, cluster: Cluster, echo: bool):
        self._ctx = ctx
        self._cluster = cluster
        self._paths = ProjectPaths(state.constellation.name, cluster.name)
        self._echo = echo

    def _get_config(self):
        with open(self._paths.talosconfig_file()) as talosconfig_file:
            return dict(yaml.safe_load(talosconfig_file))

    def _patch_kubespan(self, enabled: bool):
        self._ctx.run("talosctl --context {} patch mc -p @patch-templates/kubespan/common.pt.yaml".format(
            self._cluster.name
        ), echo=self._echo)

    def patch(self, patch_file_path: str, nodes: list = None, cluster: Cluster = None):
        cluster_name = self._cluster.name
        if cluster is not None:
            cluster_name = cluster.name

        node_cmd = ""
        if nodes is not None:
            node_cmd = "--nodes {}".format(",".join(nodes))

        self._ctx.run("talosctl --context {} {} patch mc -p @{}".format(
            cluster_name,
            node_cmd,
            patch_file_path
        ), echo=self._echo)

    def patch_nodes(self, patch_file_path: str, cluster: Cluster = None):
        self.patch(patch_file_path, self.get_nodes(), cluster)

    def patch_endpoints(self, patch_file_path: str, cluster: Cluster = None):
        self.patch(patch_file_path, self.get_endpoints(), cluster)

    def get_nodes(self) -> list:
        return self._get_config()['contexts'][self._cluster.name]['nodes']

    def get_endpoints(self) -> list:
        return self._get_config()['contexts'][self._cluster.name]['endpoints']


