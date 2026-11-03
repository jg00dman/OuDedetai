"""Optional standalone OpenSAPI installation and Logos-session ownership."""
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import requests

ASSET = 'OpenSAPI-x86_64.AppImage'
REPOSITORY = 'https://api.github.com/repos/jg00dman/opensapi'


class Speech:
    def __init__(self, app):
        self.app = app
        self.session = None

    @property
    def binary(self):
        return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'OpenSAPI' / ASSET

    def command(self, *args):
        return [str(self.binary), *args]

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
        current = False
        if self.binary.exists():
            probe = subprocess.run(self.command('--protocol-version'), env=self.environment(),
                                   capture_output=True, text=True, timeout=15)
            current = probe.returncode == 0 and probe.stdout.strip() == '2'
        if not current or not manifest.exists():
            if self.app.logos.logos_state != State.STOPPED:
                raise RuntimeError('Close Logos before installing speech support')
            if not current:
                self.download()
            with tempfile.TemporaryFile() as output:
                subprocess.run(self.command('--wine-prefix', self.app.conf.wine_prefix,
                    '--wine', self.app.conf.wine_binary, '--install-only'), env=self.environment(),
                    stdout=output, stderr=output, check=True, timeout=240)
        subprocess.Popen(self.command('--configure'), env=self.environment(), start_new_session=True)

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
        if not self.binary.exists():
            raise RuntimeError('Use Configure speech first')
        session = self.session or uuid.uuid4().hex
        try:
            subprocess.run(self.command('--acquire-session', session, '--owner-pid', str(os.getpid())),
                           env=self.environment(), check=True, timeout=100,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except BaseException:
            # A controller may finish acquiring after the launcher timed out.
            self.session = session
            self.stop()
            raise
        self.session = session

    def stop(self):
        if self.session is not None:
            try:
                subprocess.run(self.command('--release-session', self.session), env=self.environment(),
                               check=True, timeout=100, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                logging.exception('Could not release speech session; OpenSAPI also checks owner lifetime')
            self.session = None


def configure(app):
    if not app.is_installed():
        app.status('Install Logos before configuring speech')
        return
    try:
        app.logos.speech.configure()
    except (OSError, ValueError, RuntimeError, requests.RequestException, subprocess.SubprocessError) as error:
        logging.exception('Speech configuration failed')
        app.status(f'Speech configuration failed: {error}')
