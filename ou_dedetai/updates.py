"""Shared update ordering and first-run installation verification for all frontends."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import cast

from ou_dedetai import constants, installer, runtime, utils, wine
from ou_dedetai.app import App, UserExitedFromAsk


@dataclass
class UpdatePlan:
    od: bool = False
    runtime: runtime.RuntimeOption | None = None
    logos: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def components(self) -> list[str]:
        return (['OD'] if self.od else []) + (['Runtime' + (' (Testing)' if self.runtime.prerelease else '')]
                                             if self.runtime else []) + (['Logos'] if self.logos else [])


def custom_runtime(app: App) -> bool:
    raw = app.conf._raw
    if raw.wine_binary_code and raw.wine_binary_code.startswith('Custom'):
        return True
    if raw.wine_runtime_url:
        return '/faithlife-community/wine-appimages/' not in raw.wine_runtime_url.lower()
    return not app.conf.is_wine_binary_in_distribution


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _version(value: str) -> tuple[int, ...]:
    # Release tags include Wine branch/build labels that aren't PEP 440 versions.
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', value)
    return tuple(int(p or 0) for p in match.groups()) if match else ()


def runtime_update(app: App, *, refresh: bool = False) -> runtime.RuntimeOption | None:
    raw = app.conf._raw
    custom = custom_runtime(app)
    format = ('appimage' if not custom and raw.wine_binary_code != 'BundleFallback'
              and app.conf.wine_appimage_path else 'bundle')
    releases = app.conf._network.wine_runtime_releases(format, refresh=refresh)
    current_date = _date(raw.wine_runtime_published_at)
    current_version = raw.wine_runtime_version
    if not current_version and not custom:
        probe, _ = wine.get_wine_release(app.conf.wine_binary)
        current_version = f'{probe.major}.{probe.minor}' if probe else None
    for release in (releases.latest, releases.pre_release):
        if release is None:
            continue
        if not custom:
            # A stable release promoted from the installed testing build is preferred too.
            promotion = (release.version == raw.wine_runtime_version
                         and raw.wine_runtime_prerelease and not release.prerelease)
            if release.download_url == raw.wine_runtime_url and not promotion:
                continue
            release_date = _date(release.published_at)
            migration = (raw.wine_binary_code == 'BundleFallback' and release.version == raw.wine_runtime_version
                         and not release.download_url.lower().endswith('.appimage'))
            if not promotion and not migration:
                if current_date and release_date:
                    if release_date <= current_date:
                        continue
                elif current_version and _version(release.version) <= _version(current_version):
                    continue
        return runtime.RuntimeOption(
            'Testing build' if release.prerelease else 'Recommended release',
            Path(app.conf.download_dir) / Path(release.download_url).name,
            version=release.version, prerelease=release.prerelease,
            download_url=release.download_url, release=release,
            choice=(constants.WINE_TESTING_APPIMAGE_SIGIL if release.prerelease
                    else constants.WINE_RECOMMENDED_APPIMAGE_SIGIL) if format == 'appimage'
            else (constants.WINE_TESTING_TARBALL_SIGIL if release.prerelease
                  else constants.WINE_RECOMMENDED_TARBALL_SIGIL))
    return None


def check_updates(app: App, *, refresh: bool = False) -> UpdatePlan:
    plan = UpdatePlan()
    try:
        if constants.RUNMODE == 'binary':
            if refresh:
                app.conf._network.refresh_app_latest_version(app.conf.app_release_channel)
            plan.od = utils.compare_logos_linux_installer_version(app) == utils.VersionComparison.OUT_OF_DATE
    except Exception:
        logging.exception('Could not check OD updates')
        plan.errors.append('OD')
    if app.is_installed():
        try:
            plan.runtime = runtime_update(app, refresh=refresh)
        except Exception:
            logging.exception('Could not check runtime updates')
            plan.errors.append('Runtime')
        try:
            if refresh:
                app.conf._network._cache.faithlife_product_releases.clear()
            if not app.conf.is_installed_faithlife_product_release_latest:
                releases = app.conf.faithlife_product_releases
                plan.logos = releases[0] if releases else None
        except Exception:
            logging.exception('Could not check Logos updates')
            plan.errors.append('Logos')
    return plan


def verify_installation(app: App) -> bool:
    """Mark the OD version only after required maintenance succeeds."""
    if not app.is_installed() or app.conf._raw.last_verified_od_version == constants.LLI_CURRENT_VERSION:
        return True
    lock = runtime.selection_lock(app)
    if not lock.acquire(blocking=False):
        app.status('Finish the current operation before verifying the installation.')
        return False
    try:
        runtime._ensure_stopped(app)
        app.status('Verifying installation setup for this version of OD…')
        installer.verify_installation(cast(App, runtime._RuntimeDownloadApp(app)))
        app.conf.mark_installation_verified()
        app.status('Installation setup verified.', 100)
        return True
    except Exception as error:
        logging.exception('Installation verification failed')
        app.info(f'Installation verification could not finish: {error}\n'
                 'Runtime and Logos updates are paused. Verification will be retried on the next run.')
        return False
    finally:
        lock.release()


def startup(app: App) -> None:
    verify_installation(app)
    plan = check_updates(app)
    app._available_updates = plan
    app._config_updated_event.set()


def _confirm_runtime(app: App, option: runtime.RuntimeOption) -> bool:
    if custom_runtime(app):
        return app.approve('You currently have a custom runtime. Updating will replace it with the '
                           f'recommended {"testing" if option.prerelease else "release"} bundle '
                           f'({option.version}). Are you sure you want to update?')
    if option.prerelease:
        return app.approve(f'A newer testing build ({option.version}) is available. '
                           'This is a pre-release. Update to this testing build?')
    return app.approve(f'Update Runtime to {option.version}?')


def update_runtime(app: App) -> None:
    if not verify_installation(app):
        return
    option = runtime_update(app, refresh=True)
    if option is None:
        app.info('No runtime update is available.')
        return
    if not _confirm_runtime(app, option):
        return
    lock = runtime.selection_lock(app)
    if not lock.acquire(blocking=False):
        app.info('Finish the current installation, update, or runtime selection first.')
        return
    try:
        runtime.activate_option(app, option)
    finally:
        lock.release()


def update_all(app: App) -> None:
    """OD alone; after restart and verification, Runtime before Logos."""
    plan = check_updates(app, refresh=True)
    if plan.od:
        lock = runtime.selection_lock(app)
        if not lock.acquire(blocking=False):
            app.info('Finish the current installation, update, or runtime selection first.')
            return
        try:
            if app.approve('Update OD first and restart? Runtime and Logos updates will remain pending '
                           'until the new version has verified the installation.'):
                utils.update_to_latest_lli_release(app)
        finally:
            lock.release()
        return
    if not verify_installation(app):
        return
    if not plan.components:
        app.info('No updates are available.' + (' Could not check: ' + ', '.join(plan.errors) if plan.errors else ''))
        return
    if not app.approve('Available updates: ' + ', '.join(plan.components) + '. Continue?'):
        return
    if plan.runtime and not _confirm_runtime(app, plan.runtime):
        plan.runtime = None  # Declining a replacement must not block a separately approved Logos update.
    lock = runtime.selection_lock(app)
    if not lock.acquire(blocking=False):
        app.info('Finish the current installation, update, or runtime selection first.')
        return
    try:
        runtime._ensure_stopped(app)
        if plan.runtime:
            runtime.activate_option(app, plan.runtime)
        if plan.logos:
            app.conf.faithlife_product_release = plan.logos
            installer._install(cast(App, runtime._RuntimeDownloadApp(app)))
        app.status('Updates complete.', 100)
    except UserExitedFromAsk:
        pass
    except Exception as error:
        logging.exception('Update stopped')
        app.info(f'Update stopped: {error}\nLater updates have been left pending.')
    finally:
        lock.release()
        app._available_updates = check_updates(app)
        app._config_updated_event.set()
