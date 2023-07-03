import logging
import os
from glob import glob

from tasks.models.ConstellationSpecV01 import Constellation, Cluster
from tasks.models.DirTree import DirTree
from tasks.models.LocalState import KIND_CLUSTER_NAME

CONSTELLATION_FILE_SUFFIX = '.constellation.yaml'


def get_constellation_by_name(name: str) -> Constellation:
    conf_dir = DirTree()
    with open(conf_dir.root(path=[name + CONSTELLATION_FILE_SUFFIX])) as constellation_file:
        return Constellation.parse_raw(constellation_file.read())


def get_constellation_clusters(constellation: Constellation = None) -> list[Cluster]:
    clusters = list()
    clusters.append(constellation.bary)
    clusters.extend(constellation.satellites)
    return clusters


def get_cluster_by_name(cluster_name: str, constellation: Constellation = None) -> Cluster:
    if cluster_name == constellation.bary.name:
        return constellation.bary

    for satellite in constellation.satellites:
        if satellite.name == cluster_name:
            return satellite

    if cluster_name == KIND_CLUSTER_NAME:
        return Cluster(name=KIND_CLUSTER_NAME)

    logging.fatal("Cluster: {} not specified in constellation {}".format(cluster_name, constellation.name))


# def constellation_create_dirs(cluster: Cluster):
#     """
#     Create directory structure in ~/$GOCY_ROOT/[constellation_name], compatible with ArgoCD
#     """
#     conf_dir = get_conf_dir(cluster=cluster)
#     paths = set()
#     paths.add(conf_dir.argo_infra())
#     paths.add(conf_dir.argo_apps())
#
#     for directory in paths:
#         os.makedirs(directory, exist_ok=True)


def get_constellation_spec_file_paths(config_root, constellation_wildcard='*' + CONSTELLATION_FILE_SUFFIX):
    available_constellation_config_file_names = glob(
        os.path.join(
            config_root,
            constellation_wildcard)
    )

    for available_constellation_config_file_name in available_constellation_config_file_names:
        with open(available_constellation_config_file_name) as available_constellation_config_file:
            yield available_constellation_config_file
