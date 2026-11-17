"""Fill ${VARIABLE} placeholders in a template from the environment.

    python3 scripts/replace_env.py path/to/file.json.tmpl            # writes path/to/file.json
    python3 scripts/replace_env.py path/to/file.json.tmpl out.json   # writes out.json

Refuses to run when any placeholder has no value, so an unset variable can never turn into a broken ARN
or an IAM policy that silently allows nothing.
"""
import os
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render(text, env=None):
    env = os.environ if env is None else env
    missing = sorted({name for name in PLACEHOLDER.findall(text) if not env.get(name)})
    if missing:
        raise SystemExit("missing or empty variables: " + ", ".join(missing) +
                         "\nLoad your environment first:  set -a; source .env; set +a")
    return PLACEHOLDER.sub(lambda m: env[m.group(1)], text)


def main(argv):
    if not 1 <= len(argv) <= 2:
        raise SystemExit(__doc__)
    source = Path(argv[0])
    target = Path(argv[1]) if len(argv) == 2 else source.with_suffix("") if source.suffix == ".tmpl" else None
    if target is None:
        raise SystemExit("give a destination, or use a file name ending in .tmpl")
    target.write_text(render(source.read_text()))
    print(f"wrote {target}")


if __name__ == "__main__":
    main(sys.argv[1:])
