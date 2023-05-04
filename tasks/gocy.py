import os

from invoke import task

from tasks.helpers import get_config_dir


@task()
def init(ctx):
    """
    Create gocy config dir, by default: ${HOME}/.gocy
    Defined in .env -> GOCY_DEFAULT_ROOT
    """
    if os.path.isdir(get_config_dir()):
        print("Config directory {} already exists, skipping.".format(get_config_dir()))
        return

    templates = 'templates'
    ctx.run("mkdir {}".format(get_config_dir()), echo=True)
    ctx.run("cp {} {}".format(
        os.path.join(templates, 'config.yaml'),
        os.path.join(get_config_dir())
    ), echo=True)
    ctx.run("cp {} {}".format(
        os.path.join(templates, 'secrets.yaml'),
        os.path.join(get_config_dir())
    ), echo=True)

