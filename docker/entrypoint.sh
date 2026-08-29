#!/bin/sh
set -eu

program_dir=/app/program
venv_dir="$program_dir/.venv"
browser_dir=${PLAYWRIGHT_BROWSERS_PATH:-/app/browser}
data_dir=${AUTOSURF_DATA_DIR:-/app/data}
pid_file=/tmp/autosurf-app.pid
restart_file=/tmp/autosurf-restart-requested
upgrade_lock=/tmp/autosurf-upgrade-in-progress

mkdir -p "$HOME" "$data_dir" "$program_dir" "$browser_dir"

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

chrome_executable=${AUTOSURF_BROWSER_EXECUTABLE_PATH:-/usr/bin/google-chrome-stable}
if [ ! -x "$chrome_executable" ]; then
    echo "Google Chrome runtime is missing: $chrome_executable" >&2
    exit 1
fi

audio_sink=${AUTOSURF_AUDIO_SINK:-autosurf}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/tmp/autosurf-runtime}
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
pulse_socket="$XDG_RUNTIME_DIR/pulse/native"
rm -f "$XDG_RUNTIME_DIR/pulse/pid" "$pulse_socket"
pulseaudio --daemonize=no --exit-idle-time=-1 --log-target=stderr &
pulse_pid=$!
export PULSE_SERVER="unix:$pulse_socket"
pulse_ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if pactl info >/dev/null 2>&1; then
        pulse_ready=1
        break
    fi
    if ! kill -0 "$pulse_pid" 2>/dev/null; then
        break
    fi
    sleep 0.25
done
if [ "$pulse_ready" -ne 1 ]; then
    echo "PulseAudio failed to become ready at $pulse_socket" >&2
    kill -TERM "$pulse_pid" 2>/dev/null || true
    wait "$pulse_pid" 2>/dev/null || true
    exit 1
fi
if ! pactl list short sinks | awk '{print $2}' | grep -Fxq "$audio_sink"; then
    pactl load-module module-null-sink \
        sink_name="$audio_sink" rate=48000 channels=2 \
        sink_properties=device.description=AutoSurf >/dev/null
fi
pactl set-default-sink "$audio_sink"
export PULSE_SINK="$audio_sink"
export AUTOSURF_AUDIO_SOURCE=${AUTOSURF_AUDIO_SOURCE:-$audio_sink.monitor}

terminate_child() {
    if [ -f "$pid_file" ]; then
        child_pid=$(cat "$pid_file")
        kill -TERM "$child_pid" 2>/dev/null || true
    fi
    kill -TERM "$pulse_pid" 2>/dev/null || true
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
