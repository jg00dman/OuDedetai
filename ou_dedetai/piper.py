"""Opt-in management of the separately packaged OpenSAPI Piper service."""
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import psutil

from ou_dedetai.constants import PROMPT_OPTION_FILE


BACKEND_RELEASE = 'piper-backend-41387876573-1'
BACKEND_SHA256 = 'ad86e29128e65e3670ad94acc86fb4c59199a536fcbc7507c77831cf9763681f'
BACKEND_URL = (f'https://github.com/jg00dman/opensapi/releases/download/{BACKEND_RELEASE}/'
               'opensapi-piper-linux-x86_64.tar.xz')


class PiperManager:
    def __init__(self, app):
        self.app = app

    @property
    def directory(self):
        return Path(self.app.conf.install_dir) / 'data' / 'opensapi'

    @property
    def record(self):
        return self.directory / 'server.json'

    def health(self):
        # Never use a configured HTTP proxy for loopback requests.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open('http://127.0.0.1:5000/health', timeout=1) as response:
                data = json.load(response)
            return data if data.get('service') == 'opensapi-piper' and data.get('ready') else None
        except (OSError, ValueError, urllib.error.URLError):
            return None

    def owned_process(self):
        try:
            data = json.loads(self.record.read_text())
            process = psutil.Process(data['pid'])
            if process.create_time() != data['created']:
                return None
            args = process.cmdline()
            if '--instance' not in args or args[args.index('--instance') + 1] != data['instance']:
                return None
            return process
        except (OSError, ValueError, KeyError, IndexError, psutil.Error):
            return None

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / 'server.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._start()

    def _start(self):
        model = Path(self.app.conf.piper_model).expanduser().resolve()
        binary = Path(self.app.conf.piper_binary).expanduser().resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError('Choose the opensapi-piper executable in Piper settings first')
        if not model.is_file() or not Path(str(model) + '.json').is_file():
            raise RuntimeError('Piper needs both the ONNX model and its matching JSON file')
        existing = self.health()
        if existing:
            if existing.get('model') != model.name:
                raise RuntimeError('A Piper server with a different voice is already running')
            logging.info('Using an existing Piper server; it will not be stopped unless owned by this installation')
            return
        if self.owned_process():
            raise RuntimeError('The managed Piper server is running but not ready; stop it before restarting')
        instance = uuid.uuid4().hex
        with (self.directory / 'piper.log').open('ab') as log:
            process = subprocess.Popen([str(binary), '--model', str(model), '--instance', instance],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        try:
            created = psutil.Process(process.pid).create_time()
            self.record.write_text(json.dumps({'pid': process.pid, 'created': created, 'instance': instance}))
            deadline = time.monotonic() + 65
            while process.poll() is None and time.monotonic() < deadline:
                health = self.health()
                if health and health.get('instance') == instance:
                    return
                time.sleep(0.2)
            raise RuntimeError(f'Piper did not become ready; see {self.directory / "piper.log"}')
        except BaseException:
            self._stop()
            raise

    def stop(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / 'server.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._stop()

    def _stop(self):
        process = self.owned_process()
        if process:
            try:
                # The managed backend owns this new session, including its inference child.
                if os.getpgid(process.pid) != process.pid:
                    raise RuntimeError('Refusing to stop a server outside its own process group')
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except psutil.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.record.unlink(missing_ok=True)


def install(app):
    """Install a pinned prebuilt backend and voice, without touching system Python."""
    from ou_dedetai.logos import State
    import platform
    if platform.machine() not in ('x86_64', 'AMD64'):
        app.status('The packaged Piper beta currently supports x86-64 Linux only')
        return
    if app.logos.logos_state != State.STOPPED:
        app.status('Close Logos before installing Piper Read Aloud')
        return
    if not app.approve('Download and install the separate Piper beta (about 145 MB), including the '
                       'MIT-declared LJSpeech voice trained from public-domain data? '
                       'The package includes licence notices; Piper is GPL-3.0-or-later.'):
        return
    directory = app.logos.piper.directory
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / BACKEND_RELEASE
    try:
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=directory) as temporary:
                archive = Path(temporary) / 'backend.tar.xz'
                digest = hashlib.sha256()
                deadline = time.monotonic() + 300
                with urllib.request.urlopen(BACKEND_URL, timeout=30) as response, archive.open('wb') as output:
                    while chunk := response.read(1024 * 1024):
                        if time.monotonic() > deadline:
                            raise TimeoutError('Backend download timed out')
                        digest.update(chunk)
                        output.write(chunk)
                if digest.hexdigest() != BACKEND_SHA256:
                    raise RuntimeError('Backend checksum mismatch; nothing was installed')
                with tarfile.open(archive) as package:
                    package.extractall(Path(temporary) / 'unpacked', filter='data')
                unpacked = Path(temporary) / 'unpacked/opensapi-piper'
                if not (unpacked / 'opensapi-piper').is_file():
                    raise RuntimeError('Incomplete Piper package')
                unpacked.rename(target)
        register(app, str(target / 'opensapi-piper'),
                 str(target / 'voices/en_US-ljspeech-medium.onnx'))
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        logging.exception('Piper installation failed')
        app.status(f'Piper installation failed: {error}')


def configure(app):
    from ou_dedetai.logos import State
    if app.logos.logos_state != State.STOPPED:
        app.status('Close Logos before configuring its Read Aloud voice')
        return
    binary = app.ask('Select opensapi-piper from the extracted backend package', [PROMPT_OPTION_FILE])
    model = app.ask('Select the Piper .onnx voice model', [PROMPT_OPTION_FILE])
    if not Path(binary).is_file() or not os.access(binary, os.X_OK):
        app.status('The selected Piper executable is not executable')
        return
    if not Path(model).is_file() or not Path(model + '.json').is_file():
        app.status('The model and its matching .onnx.json file are both required')
        return
    register(app, binary, model)


def register(app, binary, model):
    env = os.environ.copy()
    env.update(WINEPREFIX=app.conf.wine_prefix, APPIMAGE_EXTRACT_AND_RUN='1')
    try:
        info = subprocess.run([app.conf.wine_binary, '--opensapi-info'], env=env,
                              capture_output=True, text=True, check=True, timeout=30)
        if 'OpenSAPI' not in info.stdout:
            raise RuntimeError('Select an OpenSAPI-enabled Wine AppImage first')
        subprocess.run([app.conf.wine_binary, '--opensapi-register', model + '.json'],
                       env=env, capture_output=True, check=True, timeout=200)
        subprocess.run([app.conf.wine_binary, 'reg.exe', 'add', r'HKCU\Software\Wine\DllOverrides',
                        '/v', 'sapi', '/t', 'REG_SZ', '/d', 'builtin', '/f', '/reg:64'],
                       env=env, capture_output=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        logging.exception('Piper registration failed')
        app.status(f'Piper configuration failed: {error}')
        return
    app.conf.piper_binary = str(Path(binary).resolve())
    app.conf.piper_model = str(Path(model).resolve())
    app.conf.piper_enabled = True
    app.status('Piper Read Aloud enabled for this Logos prefix; it will start and stop with Logos')


def start(app):
    try:
        app.logos.piper.start()
        app.status('Piper is ready')
    except Exception as error:
        logging.exception('Could not start Piper')
        app.status(f'Piper could not start: {error}. Logos can still run without speech.')


def stop(app):
    app.logos.piper.stop()
    app.status('Managed Piper server stopped; externally managed servers are left running')


def disable(app):
    app.conf.piper_enabled = False
    stop(app)
