import logging
import os
import sys
from glob import glob

from tasks.dao.ProjectPaths import ProjectPaths
from tasks.models.ConstellationSpecV01 import Constellation, Cluster
from tasks.models.Defaults import CONSTELLATION_FILE_SUFFIX, KIND_CONTEXT_NAME


class ConstellationSpecCtrl:
    _project_path: ProjectPaths
    _constellation_name: str

    def __init__(self, project_path: ProjectPaths = None, constellation_name: str = None):
        self._project_path = project_path
        self._constellation_name = constellation_name

    @property
    def constellation(self) -> Constellation:
        with open(self._project_path.constellation_file(self._constellation_name)) as constellation_file:
            return Constellation.parse_raw(constellation_file.read())

    def constellation_except(self, cluster: Cluster) -> list[Cluster]:
        _constellation = list(self.constellation)
        _constellation.remove(cluster)
        return _constellation

    def satellites_except(self, cluster: Cluster) -> list[Cluster]:
        _satellites = list(self.constellation.satellites)
        _satellites.remove(cluster)
        return _satellites

    def get_cluster_by_name(self, cluster_name: str) -> Cluster:
        for cluster in self.constellation:
            if cluster.name == cluster_name:
                return cluster

        if cluster_name in KIND_CONTEXT_NAME:
            return Cluster(name=KIND_CONTEXT_NAME)

        logging.fatal("Cluster: {} not specified in constellation {}".format(cluster_name, self.constellation.name))
        sys.exit(1)


def get_constellation_spec_file_paths(
        project_paths: ProjectPaths = None,
        constellation_wildcard='*' + CONSTELLATION_FILE_SUFFIX):
    if project_paths is None:
        project_paths = ProjectPaths()

    available_constellation_config_file_names = glob(
        os.path.join(
            project_paths.project_root(),
            constellation_wildcard)
    )

    for available_constellation_config_file_name in available_constellation_config_file_names:
        with open(available_constellation_config_file_name) as available_constellation_config_file:
            yield available_constellation_config_file
