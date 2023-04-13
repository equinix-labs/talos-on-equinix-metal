import os

from invoke import Collection

from tasks_pkg import apps, network, cluster


ns = Collection()
ns.add_collection(cluster)
ns.add_collection(network)
ns.add_collection(apps)

ns.configure({
    'tasks': {
        'search_root': os.environ.get('TOEM_PROJECT_ROOT')
    },
    'core': {
        'all_ips_file_name': 'secrets/all-ips.yaml'
    }
})
