class HelmApp:
    name: str
    values_file_path: str

    def __init__(self, name: str, values_file_path: str):
        self.name = name
        self.values_file_path = values_file_path


class HelmValueFiles:
    """
    Poor man's solution to Helm chicken and egg problem with CRD management.
    If a chart
    """
    app: HelmApp
    deps: list[HelmApp]

    def __init__(self, name: str, values_file_path: str):
        self.app = HelmApp(name, values_file_path)
        self.deps = list()

    def add_dependency(self, name: str, values_file_path: str):
        self.deps.append(HelmApp(name, values_file_path))
        self.deps = sorted(self.deps, key=lambda d: d.values_file_path)
