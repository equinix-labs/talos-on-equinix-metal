from invoke import task


@task()
def use_kind_cluster_context(ctx, kind_cluster_name="kind-toem-capi-local"):
    """
    Switch k8s context to local(kind) management(ClusterAPI) cluster
    """
    ctx.run("kconf use {}".format(kind_cluster_name), echo=True)
