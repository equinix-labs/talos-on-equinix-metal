import base64
import json
import os

import yaml


def str_presenter(dumper, data):
    """configures yaml for dumping multiline strings
    Ref: https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data"""
    lines = data.splitlines()
    if len(lines) > 1:  # check for multiline string
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


def get_secrets_dir():
    return os.path.join(
        os.environ.get('TOEM_PROJECT_ROOT'),
        os.environ.get('TOEM_SECRETS_DIR')
    )


def get_cpem_config():
    return {
        'apiKey': os.environ.get('PACKET_API_KEY'),
        'projectID': os.environ.get('PROJECT_ID'),
        'eipTag': '',
        'eipHealthCheckUseHostIP': True
    }


def get_cpem_config_yaml():
    return base64.b64encode(
        json.dumps(get_cpem_config()).encode('ascii'))


def get_cp_vip_address():
    with open(os.path.join(
        get_secrets_dir(),
        'ip-cp-addresses.yaml'
    ), 'r') as cp_address:
        return yaml.safe_load(cp_address)[0]


def get_cluster_name():
    return os.environ.get('CLUSTER_NAME')
