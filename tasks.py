import os

from invoke import Collection, task

from tasks_pkg import apps, network, cluster, equinix_metal, k8s_context
from tasks_pkg.helpers import get_secrets_dir

ns = Collection()
ns.add_collection(cluster)
ns.add_collection(network)
ns.add_collection(apps)
ns.add_collection(equinix_metal)
ns.add_collection(k8s_context)


@task()
def test(ctx):
    print(ctx.constellation)


ns.add_task(test)


ns.configure({
    'tasks': {
        'search_root': os.environ.get('TOEM_PROJECT_ROOT')
    },
    'core': {
        'secrets_dir': get_secrets_dir()
    },
    'equinix_metal': {
        'all_ips_file_name': os.path.join(get_secrets_dir(), 'all-ips.yaml')
    }
})
