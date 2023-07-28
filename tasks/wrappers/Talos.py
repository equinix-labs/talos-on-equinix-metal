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

    def get_nodes(self) -> list:
        return self._get_config()['contexts'][self._cluster.name]['nodes']



