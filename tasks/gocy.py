import glob
import os

import yaml
from invoke import task

from tasks.constellation_v01 import Constellation
from tasks.helpers import get_config_dir, get_secrets_file_name


@task()
def init(ctx):
    """
    Create gocy config dir, by default: ${HOME}/.gocy
    defined in .env -> GOCY_DEFAULT_ROOT
    and populate with default data, remember to update those files with your spec
    """
    if os.path.isdir(get_config_dir()):
        print("Config directory {} already exists, skipping.".format(get_config_dir()))
        return

    ctx.run("mkdir {}".format(get_config_dir()), echo=True)
    ctx.run("cp {} {}".format(
        os.path.join('templates', 'secrets.yaml'),
        os.path.join(get_config_dir())
    ), echo=True)
    ctx.run("cp {} {}".format(
        os.path.join('templates', 'demo.constellation.yaml'),
        os.path.join(get_config_dir())
    ), echo=True)


@task()
def secret_source(ctx):
    """
    Use as 'source <(invoke gocy.secret-source)'
    When used outside invoke, CLI apps we use expect ENVs from ${HOME}/.gocy/secrets.yaml to be present
        in current context
    """
    source = []
    with open(get_secrets_file_name()) as secrets_file:
        secrets = dict(yaml.safe_load(secrets_file))
        for name, value in secrets['env'].items():
            source.append('export {}={}'.format(name, value))

    print("\n".join(source))


@task()
def list_constellations(ctx):
    """
    List available constellation config specs (local)
    """
    available_constellation_config_file_names = glob.glob(
        os.path.join(
            get_config_dir(),
            '*.constellation.yaml')
        )

    for available_constellation_config_file_name in available_constellation_config_file_names:
        print(available_constellation_config_file_name)


@task()
def dump_config(ctx):
    test = Constellation(name='test')
    with open(os.path.join(get_config_dir(), 'test.yaml'), 'w') as test_config_file:
        test.dump_yaml(test_config_file, default_flow_style=False, tags=None)

