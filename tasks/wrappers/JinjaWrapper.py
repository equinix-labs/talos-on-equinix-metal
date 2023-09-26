import os

import jinja2
from jinja2 import Environment


class JinjaWrapper:
    _jinja: Environment

    def __init__(self, **kwargs):
        self._jinja = jinja2.Environment(undefined=jinja2.StrictUndefined, **kwargs)

    @property
    def jinja(self):
        return self._jinja

    def render_str(self, source: str, data: dict) -> str:
        with open(source) as source_file:
            template = self._jinja.from_string(source_file.read())

        rendered_list = [line for line in template.render(data).splitlines() if len(line.rstrip()) > 0]
        return os.linesep.join(rendered_list)

    def render(self, source: str, target: str, data: dict):
        with open(target, 'w') as target_file:
            target_file.write(self.render_str(source, data))

