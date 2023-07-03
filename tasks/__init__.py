import os

from invoke import Collection

from . import apps
from . import cluster
from . import metal
from . import gocy
from . import helpers
from . import network
from .helpers import get_project_root, get_secrets_dir

ns = Collection()
ns.add_collection(cluster)
ns.add_collection(network)
ns.add_collection(apps)
ns.add_collection(metal)
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
    }
})
