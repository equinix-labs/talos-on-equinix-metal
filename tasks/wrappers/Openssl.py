from invoke import Context

from tasks.dao.SystemContext import SystemContext


class Openssl:

    _state: SystemContext
    _ctx: Context
    _echo: bool

    def __init__(self, state: SystemContext, ctx: Context, echo: bool):
        self._state = state
        self._ctx = ctx
        self._echo = echo

    def create(self):
        ca_dir = self._state.project_paths.ca_dir()
        self._ctx.run("cp -n templates/openssl.cnf " + ca_dir)
        with self._ctx.cd(ca_dir):
            self._ctx.run(
                "openssl req -days 3560 -config openssl.cnf "
                "-subj '/CN={} CA' -nodes -new -x509 -keyout ca.key -out ca.crt".format(
                    self._state.secrets['env']['GOCY_DOMAIN']
                ), echo=self._echo)

