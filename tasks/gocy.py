import os

import yaml
from invoke import task

from tasks.helpers import get_config_dir, get_config_file_name, get_secrets_file_name


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
        get_config_file_name(),
        os.path.join(get_config_dir())
    ), echo=True)
    ctx.run("cp {} {}".format(
        get_secrets_file_name(),
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
