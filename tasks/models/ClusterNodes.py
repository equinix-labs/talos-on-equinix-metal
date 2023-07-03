class ClusterNodes:

    control_plane: list
    machines: list

    def __init__(self):
        self.control_plane = list()
        self.machines = list()

    def all(self) -> list:
        all_nodes = self.control_plane.copy()
        all_nodes.extend(self.machines)
        return all_nodes
