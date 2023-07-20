import os

import yaml

from tasks.models.HelmValueFiles import HelmValueFiles, HelmApp
from tasks.models.Namespaces import Namespace


class Helm:

    _ctx = None
    _echo: bool
    _namespace_file_name: str

    def __init__(self, ctx, echo: bool):
        self._ctx = ctx
        self._echo = echo
        self._namespace_file_name = 'namespace.yaml'

    def _install(self, helm_app: HelmApp,
                 namespace: Namespace = None, wait: bool = False):
        chart_dir_path = os.path.dirname(helm_app.values_file_path)
        namespace_file_path = os.path.join(chart_dir_path, self._namespace_file_name)

        if os.path.isfile(namespace_file_path):
            self._ctx.run("kubectl apply -f " + namespace_file_path, echo=True)
            with open(namespace_file_path) as namespace_file:
                namespace_cmd = "--namespace " + dict(yaml.safe_load(namespace_file))['metadata']['name']
        else:
            if namespace is None:
                namespace_cmd = "--create-namespace --namespace " + Namespace[helm_app.name].value
            else:
                namespace_cmd = "--create-namespace --namespace " + namespace.value

        command = "helm upgrade {} --dependency-update --install {} {} {} ".format(
            "--wait " if wait else '',
            namespace_cmd,
            helm_app.name,
            chart_dir_path
        )

        self._ctx.run(command, echo=self._echo)

    def template(self, helm_app: HelmApp,
                 namespace=None) -> list:
        app_directory = os.path.dirname(helm_app.values_file_path)
        namespace_file_path = os.path.join(app_directory, self._namespace_file_name)

        result = list()

        if os.path.isfile(namespace_file_path):
            with open(namespace_file_path) as namespace_file:
                namespace_manifest = dict(yaml.safe_load(namespace_file))
                result.append(namespace_manifest)

                namespace = namespace_manifest['metadata']['name']

            namespace_cmd = "--namespace " + namespace
        else:
            if namespace is None:
                namespace = helm_app.name

            namespace_cmd = "--namespace " + namespace

        self._ctx.run("helm dependency build " + app_directory, echo=self._echo)

        helm_manifest = list(yaml.safe_load_all(
            self._ctx.run("helm template {} {} {} ".format(
                namespace_cmd,
                helm_app.name,
                app_directory
            ), hide='stdout', echo=self._echo).stdout
        ))

        result.extend(helm_manifest)

        # Talos controller chokes on the '\n' in yaml
        # [talos] controller failed {
        #       "component": "controller-runtime",
        #       "controller": "k8s.ExtraManifestController",
        #       "error": "1 error occurred:\x5cn\x5ct* error updating manifests:
        #           invalid Yaml document separator: null\x5cn\x5cn"
        #   }
        # Helm does not mind those, we need to fix them.

        manifest = list()
        for document in result:
            if document is not None:
                if 'data' in document:
                    data_keys = document['data'].keys()
                    for key in data_keys:
                        if '\n' in document['data'][key]:
                            tmp_list = document['data'][key].split('\n')
                            for index, _ in enumerate(tmp_list):
                                tmp_list[index] = tmp_list[index].rstrip()
                            document['data'][key] = "\n".join(tmp_list).strip()
                manifest.append(document)

        return manifest

    def install(self, hvf: HelmValueFiles, install: bool, namespace: Namespace = None):
        if not install:
            return

        for dependency in hvf.deps:
            self._install(dependency, namespace, wait=True)

        self._install(hvf.app, namespace)
