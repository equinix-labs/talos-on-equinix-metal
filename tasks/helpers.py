import base64
import json
import os
from typing import Any

from tasks.models.ConstellationSpecV01 import Cluster


def str_presenter(dumper, data):
    """
    configures yaml for dumping multiline strings
    Ref: https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data
    """
    lines = data.splitlines()
    if len(lines) > 1:  # check for multiline string
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


def get_cpem_config():
    return {
        'apiKey': os.environ.get('PACKET_API_KEY'),
        'projectID': os.environ.get('PROJECT_ID'),
        'eipTag': '',
        'eipHealthCheckUseHostIP': True
    }


def get_cpem_config_yaml() -> str:
    return base64.b64encode(
        json.dumps(
            get_cpem_config()
        ).encode('utf-8')
    ).decode('utf-8')


def get_file_content_as_b64(filename):
    with open(filename, 'rb') as file:
        return base64.b64encode(file.read()).decode('utf-8')


def get_fqdn(name: Any, secrets: dict, cluster: Cluster):

    if type(name) == list:
        _name = ".".join(name)
    else:
        _name = name

    return "{}.{}.{}".format(
        _name,
        cluster.domain_prefix,
        secrets['env']['GOCY_DOMAIN']
    )


def user_confirmed(msg=None) -> bool:
    if msg is None:
        msg = 'Continue ?'

    msg += ' [y/N] '

    user_input = input(msg)
    return user_input.strip().lower() == 'y'
