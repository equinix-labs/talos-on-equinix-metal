from enum import Enum


class ProjectFile(Enum):
    kubeconfig = 'kubeconfig'
    talosconfig = 'talosconfig'

    def __str__(self):
        return self.value
