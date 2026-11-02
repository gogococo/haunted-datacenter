"""Local Docker launcher. Only its three Compose services are managed here."""
import argparse, json, os, pathlib, secrets, shutil, socket, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent
ALLOWED_KEYS = ('NEBIUS_API_KEY', 'TAVILY_API_KEY')


def read_keys(path):
    values = {}
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip().removeprefix('export ')
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key.strip() in ALLOWED_KEYS:
                value = value.strip()
                if value[:1] in ('"', "'") and value[-1:] == value[:1]:
                    value = value[1:-1]
                values[key.strip()] = value
    for key in ALLOWED_KEYS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    if not values.get('NEBIUS_API_KEY') and os.environ.get('NEBIUS_TOKEN_FACTORY_KEY'):
        values['NEBIUS_API_KEY'] = os.environ['NEBIUS_TOKEN_FACTORY_KEY']
    return values


def compose_environment(keys, project, port):
    # Do not inherit cloud identities, endpoint settings or Docker remote contexts.
    allowed = ('PATH', 'HOME', 'USER', 'TMPDIR', 'DOCKER_CONFIG', 'LANG', 'SSH_AUTH_SOCK')
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    private = ROOT / '.local-docker' / project
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = private / 'worker-tokens.json'
    if path.exists():
        tokens = json.loads(path.read_text())
    else:
        tokens = {key: secrets.token_urlsafe(32) for key in ('LOCAL_WORKER_TOKEN', 'LOCAL_COOLING_TOKEN')}
        with open(path, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(tokens, stream)
    env.update(keys)
    env.update(tokens)
    env['HAUNTED_LOCAL_PORT'] = str(port)
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the Haunted Datacenter with local Docker workers.')
    parser.add_argument('--local', action='store_true', required=True, help='Use local CPU training and cooling containers')
    parser.add_argument('--env-file', type=pathlib.Path, default=None, help='Tavily and Token Factory keys (default: .env.local if present, otherwise .env)')
    parser.add_argument('--port', type=int, default=8765, help='Loopback web port (default: 8765)')
    parser.add_argument('--project', default='haunted-local', help='Separate local saves/containers under this Compose project')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--stop', action='store_true', help='Stop this local game; keep saves and checkpoints')
    group.add_argument('--status', action='store_true', help='Show this local game’s containers')
    group.add_argument('--logs', action='store_true', help='Follow this local game’s logs')
    args = parser.parse_args(argv)
    import re
    if not 1 <= args.port <= 65535 or not re.fullmatch(r'haunted-[a-z0-9-]{1,48}', args.project):
        parser.error('Choose a valid port and a project name beginning with haunted-.')
    if not (ROOT / 'compose.local.yaml').exists():
        parser.error('Run from an editable installation or the repository checkout.')
    if not shutil.which('docker'):
        parser.error('Install and start Docker Desktop (or Docker Engine with Compose) first.')
    key_file = args.env_file or (ROOT / '.env.local' if (ROOT / '.env.local').exists() else ROOT / '.env')
    keys = read_keys(key_file.expanduser())
    if not (args.stop or args.status or args.logs):
        missing = [key for key in ALLOWED_KEYS if not keys.get(key) or keys[key].startswith('YOUR_')]
        if missing:
            parser.error('Set ' + ', '.join(missing) + ' in your shell or ' + str(key_file) + '.')
    env = compose_environment(keys, args.project, args.port)
    # Pin the local Docker context even if the shell currently points at a cloud daemon.
    context = 'desktop-linux' if sys.platform == 'darwin' else 'default'
    command = ['docker', '--context', context, 'compose', '--project-name', args.project,
               '--project-directory', str(ROOT), '--env-file', os.devnull, '-f', str(ROOT / 'compose.local.yaml')]
    if args.stop:
        return subprocess.call(command + ['down'], env=env)
    if args.status:
        return subprocess.call(command + ['ps'], env=env)
    if args.logs:
        return subprocess.call(command + ['logs', '--follow', '--tail', '80'], env=env)
    # A running project can be resumed without requiring its port to be free.
    check = subprocess.run(command + ['ps', '--status', 'running', '--services'], env=env, capture_output=True, text=True)
    if check.returncode:
        print('Docker is unavailable. Start Docker Desktop and try again.', file=sys.stderr)
        return 1
    if not check.stdout.strip():
        try:
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(('127.0.0.1', args.port))
        except OSError:
            parser.error('Port ' + str(args.port) + ' is in use. Choose --port with a free port.')
    print('Starting local Docker game: web, caretaker CPU worker, cooling controller.', flush=True)
    print('First launch downloads Python dependencies and the pinned base model. Later launches reuse them.', flush=True)
    result = subprocess.call(command + ['up', '--build', '--detach', '--wait', '--wait-timeout', '1200'], env=env)
    if result:
        print('Startup did not finish. Inspect: haunted-datacenter --local --project ' + args.project + ' --logs', file=sys.stderr)
        return result
    print('\nEnter the datacenter: http://127.0.0.1:' + str(args.port), flush=True)
    print('Stop with: haunted-datacenter --local --project ' + args.project + ' --stop (saves are kept).', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
