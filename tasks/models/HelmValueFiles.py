class HelmValueFiles:
    """
    Poor man's solution to Helm chicken and egg problem with CRD management.
    If a chart
    """
    app: str
    deps: list

    def __init__(self):
        self.deps = list()
