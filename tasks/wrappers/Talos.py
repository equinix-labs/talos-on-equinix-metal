import yaml

from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.models.ConstellationSpecV01 import Cluster


class Talos:

    _paths: ProjectPaths
    _cluster: Cluster

    def __init__(self, state: SystemContext, cluster: Cluster):
        self._cluster = cluster
        self._paths = ProjectPaths(state.constellation.name, cluster.name)

    def _get_config(self):
        with open(self._paths.talosconfig_file()) as talosconfig_file:
            return dict(yaml.safe_load(talosconfig_file))

    def get_nodes(self) -> list:
        return self._get_config()['contexts'][self._cluster.name]['nodes']


