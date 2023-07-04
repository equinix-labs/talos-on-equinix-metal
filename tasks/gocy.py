import os
from pprint import pprint

import yaml
from invoke import task
from pydantic import ValidationError
from tabulate import tabulate

from tasks.controllers.ConstellationCtrl import get_constellation_spec_file_paths
from tasks.dao.LocalState import LocalState
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.helpers import get_ccontext, get_cluster_spec_from_context, get_secrets_dir, get_jinja, \
    get_secrets
from tasks.helpers import get_constellation_clusters, get_constellation
from tasks.models.ConstellationSpecV01 import Constellation
from tasks.models.Defaults import KIND_CLUSTER_NAME


@task()
def init(ctx):
    """
    Create gocy config dir, by default: ${HOME}/.gocy
    defined in .env -> GOCY_DEFAULT_ROOT
    and populate with initial files; default constellation spec, secrets template, local state file.
    """
    LocalState()


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
def constellation_set(ctx, ccontext: str):
    """
    Set Constellation Context by {.name} as specified in ~/[GOCY_DIR]/*.constellation.yaml
    """
    LocalState().constellation_set(ccontext)


@task()
def constellation_get(ctx):
    """
    Get Constellation Context, as specified in ~/[GOCY_DIR]/ccontext, or
    default - jupiter
    """
    print(LocalState().constellation.name)


@task()
def constellation_list(ctx):
    """
    List available constellation config specs from ~/[GOCY_DIR]/*.constellation.yaml
    """
    headers = ['current', 'name', 'file', 'version']
    table = []
    state = LocalState()
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
def get_oidc_kubeconfig(ctx, cluster_name=None):
    """
    Generates oidc kubeconfigs to be shared with team members.
    """
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
    data.update(secrets['idp_auth']['k8s_oidc'])

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


def set_cluster_context(ctx, cluster_data, kind_cluster_name=KIND_CLUSTER_NAME):

    if type(cluster_data) is dict:
        cluster_name = cluster_data['name']
    elif type(cluster_data) is str:
        cluster_name = cluster_data
    else:
        cluster_name = ""

    constellation_spec = get_constellation_clusters()
    known_cluster_context = False
    for cluster_spec in constellation_spec:
        if cluster_name == kind_cluster_name or cluster_name == cluster_spec.name:
            known_cluster_context = True

    if not known_cluster_context:
        pprint('Cluster context unrecognised: {}'.format(cluster_name))
        return

    if 'kind' in cluster_name:
        ctx.run("kconf use " + cluster_name, echo=True)
    else:
        ctx.run("kconf use admin@" + cluster_name, echo=True)
        ctx.run("talosctl config context " + cluster_name, echo=True)


@task()
def context_set(ctx, context):
    """
    Set Talos and k8s cluster context to [context]
    """
    set_cluster_context(ctx, context)


@task()
def context_set_bary(ctx):
    """
    Switch k8s context to management(bary) cluster
    """
    constellation = get_constellation()
    set_cluster_context(ctx, constellation.bary.name)


@task()
def context_set_kind(ctx, kind_cluster_name=KIND_CLUSTER_NAME):
    """
    Switch k8s context to local(kind) management(ClusterAPI) cluster
    """
    set_cluster_context(ctx, kind_cluster_name)

