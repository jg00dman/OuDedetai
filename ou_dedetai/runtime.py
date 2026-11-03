"""Select the Wine runtime before or after installation, independently of the UI."""
import logging
import filecmp
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tarfile
import threading
from typing import cast

from ou_dedetai import constants, network, system, utils, wine
from ou_dedetai.app import App, UserExitedFromAsk


def _managed_dir(app: App) -> Path | None:
    """The install's Wine directory, or None while the install dir is still undecided.

    Never prompts: choosing Wine before installing must not ask install questions."""
    conf = app.conf
    if conf._overrides.installer_binary_dir is None and not (conf._overrides.install_dir or conf._raw.install_dir):
        return None
    return Path(conf.installer_binary_dir)


def discover_runtimes(app: App) -> dict[str, list[Path]]:
    managed = _managed_dir(app)
    images = [] if managed is None else sorted(
        p for p in managed.glob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower() == '.appimage')
    local = set()
    for directory in os.get_exec_path() + [str(Path.home() / 'bin'), '/usr/local/bin']:
        for name in ('wine', 'wine64'):
            path = Path(directory) / name
            if (path.is_file() and os.access(path, os.X_OK)
                    and (managed is None or path.parent.resolve() != managed.resolve())):
                local.add(path.absolute())
    steam_roots = [Path.home() / '.steam/steam', Path.home() / '.local/share/Steam',
                   Path.home() / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
    libraries = set(steam_roots)
    for root in steam_roots:
        manifest = root / 'steamapps/libraryfolders.vdf'
        if manifest.is_file():
            libraries.update(Path(p.replace('\\\\', '\\')) for p in
                             re.findall(r'"path"\s+"([^"]+)"', manifest.read_text()))
    proton = set()
    for root in libraries:
        builds = list((root / 'steamapps/common').glob('Proton*'))
        builds += list((root / 'compatibilitytools.d').glob('*'))
        for build in builds:
            for layout in ('files/bin', 'dist/bin'):
                for name in ('wine', 'wine64'):
                    path = build / layout / name
                    if path.is_file() and os.access(path, os.X_OK):
                        proton.add(path.absolute())
    return {'Installed AppImages': images, 'System/local Wine': sorted(local - proton),
            'Local Proton': sorted(proton)}


def _ensure_stopped(app: App) -> None:
    from ou_dedetai.logos import State
    if app.logos.logos_state in (State.STARTING, State.STOPPING) or app.logos.indexing_state in (
        State.STARTING, State.STOPPING
    ):
        raise ValueError('Wait for Logos and its indexer to stop before changing Wine.')
    if app.is_installed():
        app.logos.get_logos_pids()
    if any(p.is_running() for group in app.logos.existing_processes.values() for p in group):
        raise ValueError('Stop Logos and its indexer before changing Wine.')


def _check_version(app: App, binary: Path) -> None:
    result = subprocess.run([str(binary), '--version'], capture_output=True, text=True,
                            timeout=15, env=system.fix_ld_library_path(None))
    if result.returncode != 0:
        raise ValueError(f'Cannot run {binary}: {result.stderr.strip()}')
    match = re.search(r'wine-(\d+)\.(\d+)', result.stdout, re.IGNORECASE)
    if match:
        major, minor = map(int, match.groups())
        release = wine.WineRelease(major, minor, 'staging' if 'staging' in result.stdout.lower()
                                   else ('stable' if minor == 0 else 'devel'))
        target_release = (app.conf.installed_faithlife_product_release if app.is_installed()
                          else app.conf._raw.faithlife_product_release)
        target_version = app.conf._raw.faithlife_product_version or constants.FAITHLIFE_PRODUCT_VERSIONS[0]
        allowed, reason = wine.check_wine_rules(release, target_release, target_version)
        if allowed and major in (7, 8, 9, 10):
            return
        warning = reason if not allowed else 'This Wine version is not covered by the current compatibility rules.'
    else:
        warning = 'This runtime reports an unrecognised Wine version.'
    if not app.approve(f'{warning}\n{result.stdout.strip()}\nUse this developer runtime anyway?'):
        raise UserExitedFromAsk


def _server_for(binary: Path) -> Path | None:
    for path in (binary.parent / 'wineserver', binary.parent / 'server/wineserver',
                 binary.parent.parent / 'server/wineserver'):
        if path.is_file() and os.access(path, os.X_OK):
            return path.absolute()
    return None


ARCHIVE_SUFFIXES = ('.tar.gz', '.tgz', '.tar.xz')
COMMUNITY_CHOICES = {
    constants.WINE_RECOMMENDED_TARBALL_SIGIL: ('bundle', False),
    constants.WINE_TESTING_TARBALL_SIGIL: ('bundle', True),
    constants.WINE_RECOMMENDED_APPIMAGE_SIGIL: ('appimage', False),
    constants.WINE_TESTING_APPIMAGE_SIGIL: ('appimage', True),
}
UPSTREAM_CHOICES = {
    constants.WINE_UNTESTED_STABLE_APPIMAGE_SIGIL: 'continuous-stable',
    constants.WINE_UNTESTED_STAGING_APPIMAGE_SIGIL: 'continuous-staging',
    constants.WINE_UNTESTED_DEVELOPMENT_APPIMAGE_SIGIL: 'continuous-devel',
}


def is_archive(path: Path) -> bool:
    return path.name.lower().endswith(ARCHIVE_SUFFIXES)


def bundle_binary(directory: Path) -> Path:
    """Recognise extracted bundles without guessing among multiple Wine builds."""
    candidates = [directory / 'bin/wine', directory / 'bin/wine64']
    candidates += [directory / layout / 'wine' for layout in ('files/bin', 'dist/bin')]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    children = list(directory.glob('*/bin/wine'))
    if len(children) == 1:
        return children[0]
    raise ValueError(f'Cannot find a unique Wine executable in bundle: {directory}')


def prepare_bundle(app: App, selected: Path) -> tuple[Path, Path | None]:
    """Extract into a new directory; never unpack over a working runtime."""
    if selected.is_dir():
        return bundle_binary(selected), None
    root = Path(app.conf.wine_distribution_dir)
    root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='runtime-', dir=root))
    try:
        with tarfile.open(selected, 'r:*') as archive:
            # Python's data filter prevents extraction outside the staging directory.
            archive.extractall(destination, filter='data')
        return bundle_binary(destination), destination
    except BaseException:
        shutil.rmtree(destination)
        raise


def activate_runtime(
    app: App, selected: Path, server: Path | None = None, *,
    release: network.SoftwareReleaseInfo | None = None, prefer_bundle: bool = False,
) -> None:
    """Validate and activate any runtime; roll back links/files if persistence fails."""
    _ensure_stopped(app)
    selected = selected.expanduser().absolute()
    managed = Path(app.conf.installer_binary_dir)
    # Old configurations sometimes point at our wine/wine64/AppImage symlink.
    # Resolve those before rebuilding links so we cannot create a link to itself.
    if selected.parent == managed and selected.is_symlink():
        selected = selected.resolve(strict=True)
    if not selected.exists():
        raise ValueError(f'Wine runtime does not exist: {selected}')
    managed.mkdir(parents=True, exist_ok=True)
    snapshots: dict[Path, str | None] = {}
    created_image = None
    extracted = None
    old_mode = None
    is_image = selected.suffix.lower() == '.appimage'
    bundle = selected.is_dir() or is_archive(selected)
    try:
        if bundle:
            selected, extracted = prepare_bundle(app, selected)
        if is_image:
            if not utils.check_appimage(selected):
                raise ValueError(f'Not a supported AppImage: {selected}')
            if selected.name == app.conf.wine_appimage_link_file_name:
                raise ValueError('Choose the versioned AppImage, not the selected-runtime symlink.')
            destination = managed / selected.name
            if selected != destination:
                if destination.exists() or destination.is_symlink():
                    if not destination.is_symlink() and filecmp.cmp(selected, destination, shallow=False):
                        selected = destination
                    else:
                        raise ValueError(f'{destination} already exists. Select it or rename the new AppImage.')
                else:
                    created_image = destination
                    shutil.copy2(selected, destination)
            selected = destination
            old_mode = selected.stat().st_mode
            selected.chmod(old_mode | 0o100)
            server = managed / 'wineserver'
        else:
            if not selected.is_file() or not os.access(selected, os.X_OK):
                raise ValueError(f'Wine executable is missing or not executable: {selected}')
            server = server or _server_for(selected)
            if server is None:
                raise ValueError('Cannot locate the matching wineserver; select it explicitly.')
            server = server.expanduser().absolute()
            if not server.is_file() or not os.access(server, os.X_OK):
                raise ValueError(f'wineserver is not executable: {server}')
        _check_version(app, selected)
        _ensure_stopped(app)
        if is_image:
            targets: dict[Path, str | None] = {managed / app.conf.wine_appimage_link_file_name: './' + selected.name}
            targets.update({managed / name: './' + app.conf.wine_appimage_link_file_name
                            for name in ('wine', 'wine64', 'wineserver', 'winetricks')})
        else:
            targets = {managed / 'wine': str(selected), managed / 'wine64': str(selected),
                       managed / 'wineserver': str(server), managed / 'winetricks': None,
                       managed / app.conf.wine_appimage_link_file_name: None}
        for link in targets:
            if link.exists() and not link.is_symlink():
                # A separately installed winetricks belongs to the installation, not the old AppImage.
                if link.name == 'winetricks':
                    continue
                raise ValueError(f'Refusing to replace a non-symlink runtime file: {link}')
        for link, target in targets.items():
            if link.name == 'winetricks' and link.is_file() and not link.is_symlink():
                continue
            if target is None and not link.is_symlink():
                continue
            snapshots[link] = os.readlink(link) if link.is_symlink() else None
            if target is None:
                link.unlink(missing_ok=True)
            else:
                with tempfile.TemporaryDirectory(dir=managed) as temporary:
                    replacement = Path(temporary) / 'link'
                    replacement.symlink_to(target)
                    os.replace(replacement, link)
        assert server is not None
        code = ('AppImage' if is_image else 'Bundle') if release else 'Custom'
        # Keep AppImage classification for older configs and callers too.
        if is_image:
            code = ('BundleFallback' if prefer_bundle else 'AppImage') if release else 'CustomAppImage'
        app.conf.select_wine_runtime(str(selected), str(server), code, release=release)
    except BaseException:
        for link, previous in snapshots.items():
            link.unlink(missing_ok=True)
            if previous is not None:
                link.symlink_to(previous)
        if created_image is not None:
            created_image.unlink(missing_ok=True)
        elif old_mode is not None:
            selected.chmod(old_mode)
        if extracted is not None:
            shutil.rmtree(extracted)
        raise
    os.environ['PATH'] = f'{managed}:{os.environ.get("PATH", "")}'
    app.status(f'Selected Wine runtime: {selected}', 100)


@dataclass
class RuntimeOption:
    name: str
    path: Path | None
    current: bool = False
    recommended: bool = False
    version: str | None = None
    server: Path | None = None
    download_url: str | None = None
    prerelease: bool = False
    choice: str | None = None
    release: network.SoftwareReleaseInfo | None = None

    @property
    def label(self) -> str:
        label = self.name
        if self.version:
            label += f' — {self.version}'
        if self.current:
            label += ' (current)'
        if self.path is None and self.choice is None:
            label += ' (not found)'
        return label


def release_for_choice(app: App, choice: str) -> network.SoftwareReleaseInfo:
    choice = constants.LEGACY_WINE_SIGILS.get(choice, choice)
    if choice in UPSTREAM_CHOICES:
        url = app.conf._network.wine_appimage_upstream_url(UPSTREAM_CHOICES[choice])
        return network.SoftwareReleaseInfo(Path(url).name, url)
    format, testing = COMMUNITY_CHOICES[choice]
    releases = app.conf._network.wine_runtime_releases(format)
    release = releases.pre_release if testing else releases.latest
    if release is None:
        raise ValueError(f'No {"testing build" if testing else "release"} is available for {format}.')
    return release


def standard_options(app: App) -> list[RuntimeOption]:
    """Shared by Advanced Install and every runtime chooser."""
    result = []
    alpine = system.get_os()[0] == 'alpine'
    for choice, (format, testing) in COMMUNITY_CHOICES.items():
        if alpine and format == 'appimage':
            continue
        try:
            release = release_for_choice(app, choice)
        except Exception:
            logging.warning('Unable to retrieve %s', choice, exc_info=True)
            if not testing:
                result.append(RuntimeOption(choice, None, choice=choice, recommended=format == 'bundle'))
            continue
        name = choice
        if format == 'bundle' and release.download_url.lower().endswith('.appimage'):
            name += ' — AppImage fallback (bundle unavailable)'
        result.append(RuntimeOption(name, Path(app.conf.download_dir) / Path(release.download_url).name,
                                    recommended=not testing and format == 'bundle', version=release.version,
                                    download_url=release.download_url, prerelease=testing, choice=choice,
                                    release=release))
    if not alpine:
        result.extend(RuntimeOption(choice, None, choice=choice) for choice in UPSTREAM_CHOICES)
    return result


def _current_path(app: App) -> Path | None:
    selected = app.conf._raw.wine_binary
    if not selected or selected in COMMUNITY_CHOICES or selected in UPSTREAM_CHOICES:
        return None
    if Path(selected).is_absolute():
        return Path(selected).expanduser().absolute()
    if _managed_dir(app) is None:
        return Path(app.conf.download_dir) / Path(selected).name
    return Path(app.conf.wine_binary).expanduser().absolute()


def runtime_options(app: App) -> list[RuntimeOption]:
    options = standard_options(app)
    current = _current_path(app)
    for option in options:
        option.current = option.choice == app.conf._raw.wine_binary
    found = discover_runtimes(app)
    managed = _managed_dir(app)
    if managed is not None:
        bundles = list((managed / 'wine-distribution').glob('**/bin/wine'))
        found['Installed bundles'] = bundles
    seen = set()
    for category, paths in found.items():
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            options.append(RuntimeOption(str(path), path, current=path == current, server=_server_for(path)))
    if current is not None and not any(option.current for option in options):
        options.append(RuntimeOption(str(current), current, current=True, server=_server_for(current)))
    for option in options:
        if option.current and app.conf._raw.wine_server:
            option.server = Path(app.conf.wineserver_binary)
    return options


def runtime_version(path: Path) -> str:
    try:
        result = subprocess.run([str(path), '--version'], capture_output=True, text=True,
                                timeout=3, env=system.fix_ld_library_path(None))
        if result.returncode == 0 and result.stdout.strip():
            return ' '.join(result.stdout.split())
    except (OSError, subprocess.SubprocessError):
        pass
    return 'version unknown'


class _RuntimeDownloadApp:
    """Convert legacy app.exit download failures into recoverable errors."""
    def __init__(self, app: App):
        self.app = app

    def __getattr__(self, name):
        return getattr(self.app, name)

    def exit(self, reason: str, intended: bool = False):
        raise ValueError(reason)


def choose_for_install(app: App, option: RuntimeOption, server: Path | None = None) -> None:
    if option.choice:
        app.conf.choose_wine_for_install(option.choice)
    elif option.path is not None:
        candidate = added_runtime(option.path)
        assert candidate.path is not None
        probe = bundle_binary(candidate.path) if candidate.path.is_dir() else candidate.path
        if not is_archive(probe) and os.access(probe, os.X_OK):
            _check_version(app, probe)
        app.conf.choose_wine_for_install(str(candidate.path), str(server or candidate.server)
                                        if server or candidate.server else None)
    else:
        raise ValueError('This runtime was not found.')
    app.status(f'Wine runtime for installation: {option.name}', 100)


def activate_option(app: App, option: RuntimeOption, server: Path | None = None) -> None:
    if not app.is_installed():
        choose_for_install(app, option, server)
        return
    selected = option.path
    release = option.release
    if option.choice and release is None:
        release = release_for_choice(app, option.choice)
    url = release.download_url if release else option.download_url
    if url:
        from ou_dedetai.installer import download_appimage
        _ensure_stopped(app)
        selected = download_appimage(cast(App, _RuntimeDownloadApp(app)), Path(url).name, url)
    if selected is None:
        raise ValueError('This runtime was not found.')
    prefer_bundle = bool(option.choice and COMMUNITY_CHOICES.get(option.choice, ('', False))[0] == 'bundle')
    activate_runtime(app, selected, server or option.server, release=release, prefer_bundle=prefer_bundle)


def added_runtime(path: Path) -> RuntimeOption:
    path = path.expanduser().absolute()
    if not path.exists():
        raise ValueError(f'Wine runtime does not exist: {path}')
    if path.is_dir():
        binary = bundle_binary(path)
        return RuntimeOption(path.name, path, server=_server_for(binary))
    if is_archive(path):
        if not tarfile.is_tarfile(path):
            raise ValueError(f'Not a supported bundle archive: {path}')
        return RuntimeOption(path.name, path)
    if path.suffix.lower() == '.appimage':
        if not utils.check_appimage(path):
            raise ValueError(f'Not a supported AppImage: {path}')
        return RuntimeOption(path.name, path)
    if not os.access(path, os.X_OK):
        raise ValueError(f'Wine executable is not executable: {path}')
    return RuntimeOption('Custom Wine', path, server=_server_for(path))


def needs_server(option: RuntimeOption) -> bool:
    return (option.choice is None and option.path is not None and not option.path.is_dir()
            and not is_archive(option.path) and option.path.suffix.lower() != '.appimage' and option.server is None)


def selection_lock(app: App) -> threading.Lock:
    if not hasattr(app, '_wine_selection_lock'):
        setattr(app, '_wine_selection_lock', threading.Lock())
    lock: threading.Lock = getattr(app, '_wine_selection_lock')
    return lock


def downloads_directory() -> Path:
    downloads = Path.home() / 'Downloads'
    return downloads if downloads.is_dir() else Path.home()


def select_runtime(app: App) -> None:
    lock = selection_lock(app)
    if not lock.acquire(blocking=False):
        app.info('Finish the current installation or runtime selection first.')
        return
    try:
        while True:
            options = runtime_options(app)
            labels = {option.label: option for option in options}
            choice = app.choose_runtime('Set Runtime', [*labels, 'Custom…'],
                                        next((o.label for o in options if o.current), None))
            if choice in ('Cancel', 'Return to Main Menu'):
                return
            try:
                if choice == 'Custom…':
                    option = added_runtime(Path(app.choose_file(
                        'Choose an AppImage, bundle archive, directory, or Wine executable',
                        initial_dir=downloads_directory(), directories=True)))
                else:
                    option = labels[choice]
                    if option.current:
                        return
                if needs_server(option):
                    assert option.path is not None
                    option.server = Path(app.choose_file('Choose the matching wineserver executable',
                                                         initial_dir=option.path.parent))
                activate_option(app, option)
                return
            except UserExitedFromAsk:
                continue
            except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
                app.info(f'Wine selection failed: {error}')
    except UserExitedFromAsk:
        return
    finally:
        lock.release()
