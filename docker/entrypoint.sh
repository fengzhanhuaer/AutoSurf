#!/bin/sh
set -eu

program_dir=/app/program
venv_dir="$program_dir/.venv"
browser_dir=${PLAYWRIGHT_BROWSERS_PATH:-/app/browser}
pid_file=/tmp/autosurf-app.pid
restart_file=/tmp/autosurf-restart-requested
upgrade_lock=/tmp/autosurf-upgrade-in-progress

mkdir -p "$HOME"

if [ ! -d "$program_dir/.git" ]; then
    if [ -n "$(find "$program_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        echo "Program volume is not empty and is not an AutoSurf Git checkout" >&2
        exit 1
    fi
    git clone --branch "$AUTOSURF_BRANCH" --single-branch "$AUTOSURF_REPOSITORY" "$program_dir"
fi

# Windows bind mounts can report the checkout as root-owned to the container user.
git config --global --replace-all safe.directory "$program_dir"

if [ ! -x "$venv_dir/bin/autosurf" ]; then
    if [ -d "$venv_dir" ]; then
        echo "Removing incomplete AutoSurf virtual environment"
        rm -rf "$venv_dir"
    fi
    python -m venv "$venv_dir"
    "$venv_dir/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -e "$program_dir"
fi

mkdir -p "$browser_dir"
chromium_executable=$("$venv_dir/bin/python" - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    print(playwright.chromium.executable_path)
PY
)
if [ ! -x "$chromium_executable" ]; then
    "$venv_dir/bin/python" -m playwright install chromium
fi

terminate_child() {
    if [ -f "$pid_file" ]; then
        child_pid=$(cat "$pid_file")
        kill -TERM "$child_pid" 2>/dev/null || true
    fi
}
trap terminate_child TERM INT

while true; do
    "$venv_dir/bin/autosurf" serve &
    child_pid=$!
    echo "$child_pid" > "$pid_file"
    set +e
    wait "$child_pid"
    status=$?
    set -e
    rm -f "$pid_file"
    while [ -f "$upgrade_lock" ]; do
        sleep 1
    done
    if [ ! -f "$restart_file" ]; then
        exit "$status"
    fi
    rm -f "$restart_file"
    echo "Restarting AutoSurf after program upgrade"
done
