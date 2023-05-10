import os

from invoke import Collection

from . import apps
from . import cluster
from . import equinix_metal
from . import gocy
from . import helpers
from . import k8s_context
from . import network
from .helpers import get_project_root, get_secrets_dir

ns = Collection()
ns.add_collection(cluster)
ns.add_collection(network)
ns.add_collection(apps)
ns.add_collection(equinix_metal)
ns.add_collection(k8s_context)
ns.add_collection(gocy)


ns.configure({
    'tasks': {
        'search_root': get_project_root()
    },
    'core': {
        'secrets_dir': get_secrets_dir(),
        'ca_dir': os.path.join(
            get_secrets_dir(),
            'ca'
        )
    },
    'equinix_metal': {
        'project_ips_file_name': os.path.join(get_secrets_dir(), 'project-ips.yaml')
    }
})
