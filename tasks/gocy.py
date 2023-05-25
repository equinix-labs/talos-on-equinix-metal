import os
from pprint import pprint

import jinja2
import yaml
from invoke import task
from pydantic import ValidationError
from tabulate import tabulate

from tasks.constellation_v01 import Constellation
from tasks.helpers import get_config_dir, get_secrets_file_name, available_constellation_specs, \
    get_constellation_context_file_name, get_ccontext, get_cluster_spec_from_context, get_secrets_dir, get_jinja, \
    get_secrets


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
        os.path.join('templates', 'jupiter.constellation.yaml'),
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
def ccontext_set(ctx, ccontext: str):
    """
    Set default Constellation Context by {.name} as specified in ~/[GOCY_DIR]/*.constellation.yaml
    """
    written = False
    for available_constellation in available_constellation_specs():
        try:
            constellation = Constellation.parse_raw(available_constellation.read())
            if constellation.name == ccontext:
                with open(get_constellation_context_file_name(), 'w') as cc_file:
                    cc_file.write(ccontext)
                    written = True
        except ValidationError:
            pass

    if not written:
        print("Context not set, make sure the name is correct,"
              " and matches those defined in ~/[GOCY_DIR]/*.constellation.yaml")


@task()
def ccontext_get(ctx):
    """
    Get default Constellation Context, as specified in ~/[GOCY_DIR]/ccontext, or
    default - jupiter
    """
    print(get_ccontext())


@task()
def list_constellations(ctx):
    """
    List available constellation config specs from ~/[GOCY_DIR]/*.constellation.yaml
    """
    table = [['file', 'valid', 'name', 'version', 'ccontext']]
    ccontext = get_ccontext()
    for available_constellation in available_constellation_specs():
        row = [available_constellation.name]
        try:
            constellation = Constellation.parse_raw(available_constellation.read())
            row.append(True)
            row.append(constellation.name)
            row.append(constellation.version)
            if ccontext == constellation.name:
                row.append(True)
            else:
                row.append(False)
        except ValidationError:
            row.append(False)
        finally:
            table.append(row)

    print(tabulate(table))


@task()
def get_oidc_kubeconfig(ctx, cluster_name=None):
    if cluster_name is None:
        cluster_name = get_cluster_spec_from_context(ctx).name

    kubeconfig_dir = os.path.join(
        get_secrets_dir(),
        cluster_name
    )
    kubeconfig_file_path = os.path.join(
        kubeconfig_dir,
        cluster_name + '.kubeconfig'
    )
    with open(kubeconfig_file_path) as kubeconfig_file:
        kubeconfig = dict(yaml.safe_load(kubeconfig_file))

    jinja = get_jinja()
    with open(os.path.join('templates', 'k8s_oidc_user.yaml')) as oidc_user_tpl_file:
        oidc_user_tpl = jinja.from_string(oidc_user_tpl_file.read())

    secrets = get_secrets()
    data = {
        'cluster_name': cluster_name
    }
    data.update(secrets['idp_auth']['oidc'])

    oidc_user = yaml.safe_load(oidc_user_tpl.render(data))

    kubeconfig['users'] = [oidc_user]
    kubeconfig['contexts'][0]['context']['user'] = oidc_user['name']
    kubeconfig['contexts'][0]['name'] = "{}@{}".format('oidc', cluster_name)
    kubeconfig['current-context'] = kubeconfig['contexts'][0]['name']

    oidc_kubeconfig_file_path = os.path.join(
        kubeconfig_dir,
        cluster_name + '.oidc.kubeconfig'
    )

    with open(oidc_kubeconfig_file_path, 'w') as oidc_kubeconfig_file:
        yaml.safe_dump(kubeconfig, oidc_kubeconfig_file)
