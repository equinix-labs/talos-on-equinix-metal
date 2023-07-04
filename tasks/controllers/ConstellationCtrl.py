import logging
import os
from glob import glob

from tasks.dao.ProjectPaths import ProjectPaths
from tasks.models.ConstellationSpecV01 import Constellation, Cluster
from tasks.models.Defaults import KIND_CLUSTER_NAME, CONSTELLATION_FILE_SUFFIX


class ConstellationCtrl:

    _project_path: ProjectPaths
    _constellation_name: str

    def __init__(self, project_path: ProjectPaths, constellation_name: str):
        self._project_path = project_path
        self._constellation_name = constellation_name

    @property
    def constellation(self) -> Constellation:
        with open(self._project_path.constellation_file(self._constellation_name)) as constellation_file:
            return Constellation.parse_raw(constellation_file.read())

    def get_cluster_by_name(self, cluster_name: str) -> Cluster:
        if cluster_name == self.constellation.bary.name:
            return self.constellation.bary

        for satellite in self.constellation.satellites:
            if satellite.name == cluster_name:
                return satellite

        if cluster_name == KIND_CLUSTER_NAME:
            return Cluster(name=KIND_CLUSTER_NAME)

        logging.fatal("Cluster: {} not specified in constellation {}".format(cluster_name, self.constellation.name))


def get_constellation_spec_file_paths(constellation_dir, constellation_wildcard='*' + CONSTELLATION_FILE_SUFFIX):
    available_constellation_config_file_names = glob(
        os.path.join(
            constellation_dir,
            constellation_wildcard)
    )

    for available_constellation_config_file_name in available_constellation_config_file_names:
        with open(available_constellation_config_file_name) as available_constellation_config_file:
            yield available_constellation_config_file
