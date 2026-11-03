"""Optional standalone OpenSAPI installation and Logos-session ownership."""
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid

import requests

ASSET = 'OpenSAPI-x86_64.AppImage'
REPOSITORY = 'https://api.github.com/repos/jg00dman/opensapi'


class Speech:
    def __init__(self, app):
        self.app = app
        self.instance = None
        self.process = None
        self.lock = threading.RLock()

    @property
    def binary(self):
        return Path(self.app.conf.installer_binary_dir) / ASSET

    @property
    def settings(self):
        return Path(self.app.conf.install_dir) / 'data/opensapi/settings.json'

    def health(self):
        try:
            config = json.loads(self.settings.read_text())
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{config.get("port", 5000)}/health', timeout=1) as response:
                return json.load(response)
        except (OSError, ValueError):
            return None

    def command(self, *args):
        return [str(self.binary), '--settings', str(self.settings), *args]

    def environment(self):
        # PyInstaller's library path must not leak into the separate AppImage/Wine.
        env = os.environ.copy()
        if 'LD_LIBRARY_PATH_ORIG' in env:
            env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        else:
            env.pop('LD_LIBRARY_PATH', None)
        env['APPIMAGE_EXTRACT_AND_RUN'] = '1'
        return env

    def configure(self):
        from .logos import State
        manifest = Path(self.app.conf.wine_prefix) / 'drive_c/Program Files/OpenSAPI/install-state.json'
        if not self.binary.exists() or not manifest.exists() or not self.settings.exists():
            if self.app.logos.logos_state != State.STOPPED:
                raise RuntimeError('Close Logos before installing speech support')
            if not self.binary.exists():
                self.download()
            self.settings.parent.mkdir(parents=True, exist_ok=True)
            # Preserve the user's existing OpenSAPI voice selection on first use.
            previous = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'OpenSAPI/settings.json'
            if not self.settings.exists() and previous.exists():
                self.settings.write_bytes(previous.read_bytes())
            with tempfile.TemporaryFile() as output:
                subprocess.run(self.command('--wine-prefix', self.app.conf.wine_prefix,
                    '--wine', self.app.conf.wine_binary, '--install-only'), env=self.environment(),
                    stdout=output, stderr=output, check=True, timeout=240)
        subprocess.Popen(self.command(), env=self.environment(), start_new_session=True)

    def download(self):
        import platform
        if platform.machine() not in ('x86_64', 'AMD64'):
            raise RuntimeError('The OpenSAPI beta currently supports x86-64 Linux only')
        self.app.status('Downloading the latest standalone OpenSAPI beta…')
        response = requests.get(REPOSITORY + '/releases?per_page=100', timeout=30)
        response.raise_for_status()
        releases = sorted(response.json(), key=lambda r: r.get('published_at') or '', reverse=True)
        assets = next(({a['name']: a['browser_download_url'] for a in release['assets']}
                       for release in releases if not release['draft'] and
                       {ASSET, 'SHA256SUMS'} <= {a['name'] for a in release['assets']}), None)
        if not assets:
            raise RuntimeError('No standalone OpenSAPI release was found')
        response = requests.get(assets['SHA256SUMS'], timeout=30)
        response.raise_for_status()
        expected = next((line.split()[0] for line in response.text.splitlines()
                         if len(line.split()) == 2 and line.split()[1] == ASSET), None)
        if not expected or len(expected) != 64:
            raise RuntimeError('The release has no valid AppImage checksum')
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.binary.parent) as temporary:
            target = Path(temporary) / ASSET
            digest = hashlib.sha256()
            deadline = time.monotonic() + 600
            with requests.get(assets[ASSET], stream=True, timeout=30) as download:
                download.raise_for_status()
                with target.open('wb') as output:
                    for chunk in download.iter_content(1024 * 1024):
                        if time.monotonic() > deadline or output.tell() > 512 * 1024 * 1024:
                            raise TimeoutError('OpenSAPI download exceeded its limit')
                        output.write(chunk)
                        digest.update(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeError('OpenSAPI checksum mismatch; nothing was installed')
            target.chmod(0o755)
            target.replace(self.binary)

    def start(self):
        with self.lock:
            current = self.health()
            if current:
                if current.get('settings') != str(self.settings.resolve()) or not current.get('ready'):
                    raise RuntimeError('Another speech service is using this port; configure speech first')
                return  # Reused services are never claimed or stopped by this session.
            if not self.binary.exists() or not self.settings.exists():
                raise RuntimeError('Use Configure speech first')
            self.instance = uuid.uuid4().hex
            control = self.settings.with_suffix('.control')
            descriptor = os.open(control, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.chmod(control, 0o600)
            with os.fdopen(descriptor, 'w') as output:
                output.write(secrets.token_hex(32))
            self.settings.with_suffix('.server.json').write_text(json.dumps({
                'instance': self.instance, 'settings': str(self.settings.resolve()),
                'port': json.loads(self.settings.read_text()).get('port', 5000)}))
            with self.settings.with_suffix('.server.log').open('ab') as output:
                self.process = subprocess.Popen(self.command('--serve', '--instance', self.instance,
                    '--control-file', str(control)), env=self.environment(), stdin=subprocess.DEVNULL,
                    stdout=output, stderr=output, start_new_session=True)
            deadline = time.monotonic() + 65
            while self.process.poll() is None and time.monotonic() < deadline:
                current = self.health()
                if current and current.get('instance') == self.instance and current.get('ready'):
                    return
                time.sleep(.2)
            self.stop()
            raise RuntimeError(f'Piper could not start; see {self.settings.with_suffix(".server.log")}')

    def stop(self):
        with self.lock:
            if self.process is None:
                return
            current = self.health()
            if current and current.get('instance') == self.instance:
                try:
                    subprocess.run(self.command('--stop-server'), env=self.environment(), check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                except (OSError, subprocess.SubprocessError):
                    logging.exception('Could not stop speech gracefully')
            if self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
                except ProcessLookupError:
                    pass
            self.instance = self.process = None


def configure(app):
    if not app.is_installed():
        app.status('Install Logos before configuring speech')
        return
    try:
        app.logos.speech.configure()
    except (OSError, ValueError, RuntimeError, requests.RequestException, subprocess.SubprocessError) as error:
        logging.exception('Speech configuration failed')
        app.status(f'Speech configuration failed: {error}')
