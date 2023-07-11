import os

import yaml
from invoke import task
from pydantic import ValidationError
from tabulate import tabulate

from tasks.controllers.ClusterctlCtrl import ClusterctlCtrl
from tasks.controllers.ConstellationSpecCtrl import get_constellation_spec_file_paths
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.models.ConstellationSpecV01 import Constellation


@task()
def generate_ca(ctx, echo=False):
    """
    Generate root CA, to be used by cilium and others
    """
    state = SystemContext(ctx, echo)
    ca_dir = state.project_paths.ca_dir()

    ctx.run("cp -n templates/openssl.cnf " + ca_dir)
    with ctx.cd(ca_dir):
        ctx.run("openssl req -days 3560 -config openssl.cnf "
                "-subj '/CN={} CA' -nodes -new -x509 -keyout ca.key -out ca.crt".format(
                    os.environ.get('GOCY_DOMAIN')), echo=echo)


@task(post=[generate_ca])
def init(ctx, echo: bool = False):
    """
    Create gocy config dir, by default: ${HOME}/.gocy
    defined in .env -> GOCY_DEFAULT_ROOT
    and populate with initial files; default constellation spec, secrets template, local state file.
    """
    state = SystemContext(ctx, echo)
    clusterctl = ClusterctlCtrl(state, echo)
    clusterctl.kind_create(ctx)


@task()
def secret_source(ctx):
    """
    Use as 'source <(invoke gocy.secret-source)'
    When used outside invoke, CLI apps we use expect ENVs from ${HOME}/.gocy/secrets.yaml to be present
        in current context
    """
    source = []
    ppaths = ProjectPaths()

    with open(ppaths.secrets_file()) as secrets_file:
        secrets = dict(yaml.safe_load(secrets_file))
        for name, value in secrets['env'].items():
            source.append('export {}={}'.format(name, value))

    source.append('export {}={}'.format('TALOSCONFIG', ppaths.project_root('talosconfig')))

    print("\n".join(source))


@task()
def constellation_set(ctx, ccontext: str, echo: bool = False):
    """
    Set Constellation Context by {.name} as specified in ~/[GOCY_DIR]/*.constellation.yaml
    """
    SystemContext(ctx, echo).constellation_set(ccontext)


@task()
def constellation_get(ctx, echo: bool = False):
    """
    Get Constellation Context, as specified in ~/[GOCY_DIR]/ccontext, or
    default - jupiter
    """
    print(SystemContext(ctx, echo).constellation.name)


@task()
def constellation_list(ctx, echo: bool = False):
    """
    List available constellation config specs from ~/[GOCY_DIR]/*.constellation.yaml
    """
    headers = ['current', 'name', 'file', 'version']
    table = []
    state = SystemContext(ctx, echo)
    for constellation_spec_file_path in get_constellation_spec_file_paths():
        row = []
        try:
            constellation = Constellation.parse_raw(constellation_spec_file_path.read())
            if state.constellation == constellation:
                row.append("*")
            else:
                row.append("")
            row.append(constellation.name)
            row.append(constellation_spec_file_path.name)
            row.append(constellation.version)
            table.append(row)
        except ValidationError:
            print("Could not parse spec file: " + constellation_spec_file_path.name)

    print(tabulate(table, headers=headers))


@task()
def context_set(ctx, cluster_name: str, echo: bool = False):
    """
    Set Talos and k8s cluster context to [context]
    """
    system = SystemContext(ctx, echo)
    system.set_cluster(cluster_name)
