import binascii
import shutil

from invoke import Context

from tasks.dao.ProjectPaths import RepoPaths
from tasks.dao.SystemContext import SystemContext


def get_file_content_as_b64(filename) -> str:
    with open(filename, 'rb') as file:
        content = file.read()
        return binascii.b2a_base64(content).decode('utf-8')


class OpenSSL:

    _state: SystemContext
    _ctx: Context
    _echo: bool

    def __init__(self, state: SystemContext, ctx: Context, echo: bool):
        self._state = state
        self._ctx = ctx
        self._echo = echo

    def create(self):
        ca_dir = self._state.project_paths.ca_dir()
        repo_paths = RepoPaths()
        shutil.copy(repo_paths.openssl_cnf_file(), ca_dir)
        self._ctx.run(
            "openssl req -days 3560 -config {} -subj '/CN={} CA' -nodes -new -x509 -keyout {} -out {}".format(
                self._state.project_paths.openssl_cnf_file(),
                self._state.secrets['env']['GOCY_DOMAIN'],
                self._state.project_paths.ca_key_file(),
                self._state.project_paths.ca_crt_file()
            ), pty=True, echo=self._echo)

    def get_ca_crt_as_b64(self):
        return get_file_content_as_b64(self._state.project_paths.ca_crt_file())

    def get_ca_key_as_b64(self):
        return get_file_content_as_b64(self._state.project_paths.ca_key_file())
