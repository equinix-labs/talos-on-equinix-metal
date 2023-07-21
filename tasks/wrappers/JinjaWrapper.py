import os

import jinja2
from jinja2 import Environment


class JinjaWrapper:
    _jinja: Environment

    def __init__(self):
        self._jinja = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def render(self, source: str, target: str, data: dict):
        with open(source) as source_file:
            template = self._jinja.from_string(source_file.read())

        with open(target, 'w') as target_file:
            rendered_list = [line for line in template.render(data).splitlines() if len(line.rstrip()) > 0]
            target_file.write(os.linesep.join(rendered_list))

