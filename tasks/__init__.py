from invoke import Collection

from . import apps
from . import cluster
from . import gocy
from . import helpers
from . import metal
from . import mesh
from . import dns

ns = Collection()
ns.add_collection(cluster)
ns.add_collection(mesh)
ns.add_collection(apps)
ns.add_collection(metal)
ns.add_collection(gocy)
ns.add_collection(dns)
