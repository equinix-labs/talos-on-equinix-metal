from invoke import task

from tasks.dao.SystemContext import SystemContext
from tasks.wrappers.Harbor import Harbor


@task()
def configure(ctx, cluster_name: str = None, echo: bool = False):
    context = SystemContext(ctx, echo)
    if cluster_name is not None:
        harbor_client = Harbor(context, context.cluster(cluster_name))
    else:
        harbor_client = Harbor(context)

    harbor_client.oidc_enable()


@task()
def project_create(ctx, project_name: str, cluster_name: str = None, echo: bool = False):
    context = SystemContext(ctx, echo)
    if cluster_name is not None:
        harbor_client = Harbor(context, context.cluster(cluster_name))
    else:
        harbor_client = Harbor(context)

    harbor_client.create_project(project_name)
