from pprint import pprint

from invoke import task

from tasks_pkg.helpers import get_constellation_spec


def _use_cluster_context(ctx, cluster_data, kind_cluster_name="kind-toem-capi-local"):

    if type(cluster_data) is dict:
        cluster_name = cluster_data['name']
    elif type(cluster_data) is str:
        cluster_name = cluster_data
    else:
        cluster_name = ""

    constellation_spec = get_constellation_spec(ctx)
    known_cluster_context = False
    for cluster_spec in constellation_spec:
        if cluster_name == kind_cluster_name or cluster_name == cluster_spec['name']:
            known_cluster_context = True

    if not known_cluster_context:
        pprint('Cluster context unrecognised: {}'.format(cluster_name))
        return

    if 'kind' in cluster_name:
        ctx.run("kconf use " + cluster_name, echo=True)
    else:
        ctx.run("kconf use admin@" + cluster_name, echo=True)


@task()
def use_bary_cluster_context(ctx):
    """
    Switch k8s context to management(bary) cluster
    """
    _use_cluster_context(ctx, ctx.constellation.bary.name)


@task()
def use_kind_cluster_context(ctx, kind_cluster_name="kind-toem-capi-local"):
    """
    Switch k8s context to local(kind) management(ClusterAPI) cluster
    """
    _use_cluster_context(ctx, kind_cluster_name)
