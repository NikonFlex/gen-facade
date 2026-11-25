#!/bin/sh
set -eu
cd "$(dirname "$0")"

# Each editable install must resolve genfacade from this worktree.
if [ ! -x .venv/bin/python3 ]; then
    "${GENFACADE_PYTHON:-python3}" -m venv .venv
fi
.venv/bin/python3 -m pip install -e '.[dev]' -r tools/requirements.txt
sh tools/install_hooks.sh
printf 'Для работы в этом дереве выполните: . .venv/bin/activate\n'
