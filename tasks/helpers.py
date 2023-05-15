import base64
import glob
import json
import os
from pprint import pprint

import git
import yaml

from tasks.constellation_v01 import Constellation, Cluster


CONSTELLATION_FILE_SUFFIX = '.constellation.yaml'


def str_presenter(dumper, data):
    """
    configures yaml for dumping multiline strings
    Ref: https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data
    """
    lines = data.splitlines()
    if len(lines) > 1:  # check for multiline string
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


def get_cfg(value, default):
    if value is None:
        return default
    return value


def get_cluster_spec(ctx, name):
    for cluster_spec in get_constellation_clusters():
        if cluster_spec.name == name:
            return cluster_spec


def get_cluster_spec_from_context(ctx) -> Cluster:
    context = ctx.run("kubectl config current-context", hide='stdout', echo=True).stdout
    for cluster_spec in get_constellation_clusters():
        if cluster_spec.name in context:
            return cluster_spec

    print("k8s context: '{}' not in constellation".format(context.strip()))


def get_project_root():
    git_repo = git.Repo(os.getcwd(), search_parent_directories=True)
    return git_repo.git.rev_parse("--show-toplevel")


def get_config_dir(default_config_dir_name=".gocy"):
    default_root = os.environ.get('GOCY_DEFAULT_ROOT', None)
    if default_root is not None:
        return default_root

    return os.path.join(
        os.path.expanduser('~'),
        default_config_dir_name
    )


def get_secrets_file_name(name='secrets.yaml'):
    return os.path.join(get_config_dir(), name)


def get_secrets():
    with open(get_secrets_file_name()) as secrets_file:
        return dict(yaml.safe_load(secrets_file))['env']


def get_cpem_config():
    return {
        'apiKey': os.environ.get('PACKET_API_KEY'),
        'projectID': os.environ.get('PROJECT_ID'),
        'eipTag': '',
        'eipHealthCheckUseHostIP': True
    }


def get_cpem_config_yaml() -> str:
    return base64.b64encode(
        json.dumps(get_cpem_config()).encode('utf-8')).decode('utf-8')


def get_file_content_as_b64(filename):
    with open(filename, 'rb') as file:
        return base64.b64encode(file.read()).decode('utf-8')


def get_vips(cluster_spec, role):
    with open(os.path.join(
            get_secrets_dir(),
            cluster_spec.name,
            'ip-{}-addresses.yaml'.format(role)
    ), 'r') as cp_address:
        return yaml.safe_load(cp_address)


def get_cp_vip_address(cluster_spec):
    return get_vips(cluster_spec, 'cp')[0]


def get_cluster_name():
    return os.environ.get('CLUSTER_NAME')


def available_constellation_specs(constellation_wildcard='*' + CONSTELLATION_FILE_SUFFIX):
    available_constellation_config_file_names = glob.glob(
        os.path.join(
            get_config_dir(),
            constellation_wildcard)
    )

    for available_constellation_config_file_name in available_constellation_config_file_names:
        with open(available_constellation_config_file_name) as available_constellation_config_file:
            yield available_constellation_config_file


def get_constellation_context_file_name(name="ccontext"):
    return os.path.join(get_config_dir(), name)


def get_ccontext(default_ccontext='jupiter'):
    try:
        with open(get_constellation_context_file_name()) as cc_file:
            ccontext = cc_file.read()
            if ccontext == '':
                raise OSError
            return ccontext
    except OSError:
        return default_ccontext


def get_secrets_dir():
    return os.path.join(
        get_config_dir(),
        get_ccontext()
    )


def get_constellation(name=None) -> Constellation:
    if name is None:
        name = get_ccontext()

    with open(os.path.join(get_config_dir(), name + CONSTELLATION_FILE_SUFFIX)) as constellation_file:
        return Constellation.parse_raw(constellation_file.read())


def get_constellation_clusters(constellation: Constellation = None) -> list[Cluster]:
    clusters = list()
    if constellation is None:
        constellation = get_constellation()

    clusters.append(constellation.bary)
    clusters.extend(constellation.satellites)
    return clusters
