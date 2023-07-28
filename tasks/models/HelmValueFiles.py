import os.path


class HelmApp:
    name: str
    chart_source_dir: str
    chart_target_dir: str
    values_file_path: str

    def __init__(self, name: str, chart_source_dir: str, values_file_path: str):
        self.name = name
        self.chart_source_dir = chart_source_dir
        self.chart_target_dir = os.path.dirname(values_file_path)
        self.values_file_path = values_file_path


class HelmValueFiles:
    """
    Poor man's solution to Helm chicken and egg problem with CRD management.
    If a chart
    """
    app: HelmApp
    deps: list[HelmApp]

    def __init__(self, name: str, chart_source_dir: str, values_file_path: str):
        self.app = HelmApp(name, chart_source_dir, values_file_path)
        self.deps = list()

    def add_dependency(self, name: str, chart_source_dir: str, values_file_path: str):
        self.deps.append(HelmApp(name, chart_source_dir, values_file_path))
        self.deps = sorted(self.deps, key=lambda d: d.values_file_path)
