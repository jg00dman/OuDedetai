# Manual testing results

## Optarg testing

| Optargs | latest version tested | result | notes
| :--- | :--- | :---: | :--- |
| `-v/--version` | `main-20240426-09cb40d` | :+1: |
| `-F/--skip-fonts` | `4.0.0-alpha.6` | :+1: |
| `-a/--check-for-updates` | | |
| `-K/--skip-dependencies` | `4.0.0-alpha.6` | :+1: |
| `-V/--verbose` | `main-20240426-09cb40d` | :+1: |
| `-D/--debug` | `main-20240426-09cb40d` | :+1: |
| `-c/--config` | | |
| `-f/--force-root` | | |
| `-p/--custom-binary-path` | | |
| `-L/--delete-log` | `4.0.0-alpha.6` | :+1: |
| `--install-app` | `4.0.0-alpha.6` | :+1: |
| `--run-installed-app` | `4.0.0-alpha.6` | :+1: |
| `--run-indexing` | | |
| `--remove-library-catalog` | | |
| `--remove-index-files` | | |
| `--edit-config` | `main-20240426-09cb40d` | :-1: | gnome-text-editor symbol lookup error: /lib/x86_64-linux-gnu/libcairo.so.2: undefined symbol: FT_Get_Transform
| `--install-dependencies` | `main-20240426-09cb40d` | :+1: |
| `--backup` | | |
| `--restore` | | |
| `--update-self` | | |
| `--update-latest-appimage` | | |
| `--set-appimage` | | |
| `--get-winetricks` | | |
| `--run-winetricks` | `4.0.0-alpha.6` | :+1: |
| `--toggle-app-logging` | `4.0.0-alpha.6` | :+1: |
| `--create-shortcuts` | | |
| `--remove-install-dir` | `4.0.0-alpha.6` | :+1: |
| `--dirlink` | | |
| `--check-resources` | | |

## TUI testing

![TUI screenshot](manual-testing-tui.png)

| Option | latest version tested | result |
| :--- | :--- | :---: |
| Install [app] | `4.0.0-alpha.6` | :+1: |
| Run app | `4.0.0-alpha.6` | :+1: |
| Run indexing |||
| Remove all index files |||
| Run Winetricks | `4.0.0-alpha.6` | :+1: |
| Download/Update Winetricks |||
| Edit Config | `4.0.0-alpha.6` | :+1: |
| Back up Data |||
| Restore Data |||
| Enable/Disable [app logging] |||
| Update to Latest AppImage |||
| Set AppImage |||
| Install Dependencies |||

## GUI testing

![GUI screenshot](manual-testing-gui.png)

| Button/Action | latest version tested | result |
| :--- | :--- | :---: |
| Install [app] | `4.0.0-alpha.6` | :+1: |
| Run app | `4.0.0-alpha.6` | :+1: |
| Run indexing |||
| Remove library catalog |||
| Remove all index files |||
| Edit... [config file] | `main-20240426-09cb40d` | :-1: | Ubuntu 24.04: gnome-text-editor symbol lookup error: /lib/x86_64-linux-gnu/libcairo.so.2: undefined symbol: FT_Get_Transform
| Install [dependencies] | `main-20240426-09cb40d` | :-1: | Ubuntu 24.04: fails to prompt for password
| Backup |||
| Restore |||
| [Self-]Update |||
| Run [Update to Latest AppImage] |||
| Run [Set AppImage] |||
| Run [Winetricks] | `4.0.0-alpha.6` | :+1: |
| Download/Update [Winetricks] |||
| Enable/Disable [app logging] |||
## Runtime selection and updates (select-wine-runtime-2)

Use a test installation with Logos and its indexer stopped. Runtime activation
restores links/config on failure, but cannot undo changes Wine later makes to a prefix.

### Selection in GUI, TUI, and CLI

1. Open **Set Runtime** in the existing GUI or **Set Runtime…** in the TUI.
   Compare its standard choices with **Advanced Install**. Both must offer our
   latest stable release as recommended and latest pre-release as testing, plus
   the existing upstream AppImage and locally discovered Wine options.
2. Check the recommendation against
   https://github.com/FaithLife-Community/wine-appimages/releases.
   Prefer a bundle asset within the selected release. If that release has only
   an AppImage, clearly show the fallback; never silently install a different
   release or a source-code archive. Testing must not be the default.
3. GUI: browse with **Custom file…** or **Bundle directory…**. TUI: navigate the
   file browser and use **Use this directory** for an extracted bundle. Browse
   archives, AppImages, and Wine executables. Check spaces and brackets in names,
   parent-directory navigation, cancellation, and an 80×16 terminal.
4. Select a custom `.tar.xz`, `.tar.gz`, or `.tgz` bundle. Confirm extraction into
   its own managed directory, including libraries. Select an already-extracted
   bundle outside the installation and confirm that its complete layout is used.
5. Select an AppImage without execute permission: its managed copy must become
   executable without changing the source. Switch AppImage → bundle → AppImage;
   confirm Wine, wineserver, and winetricks use the new runtime, without stale links.
6. Select local Wine or Proton. If necessary, browse for its matching wineserver.
   Restart OD and check that the same runtime and server remain selected.
7. Try invalid archives/AppImages, missing files, failed version probes, and
   unwritable config files. The working runtime, config, and links must survive.
   Try switching with Logos or its indexer running: activation must be refused.
8. Before installation, choose a runtime and confirm that no runtime is copied,
   extracted, or downloaded until installation starts. Choosing it must not ask
   for an installation directory. Run normal and advanced installations with it.
9. CLI equivalents:
   - `oudedetai --select-wine` (also `--select-runtime`)
   - `oudedetai --set-runtime /path/to/runtime`
   - Legacy `--set-appimage /path/to/image.AppImage` remains supported.

### Unified updates and first-run verification

1. The existing GUI **Update** button lists available OD, Runtime, and Logos
   updates alongside it. It is disabled when nothing is available. **Check**
   refreshes availability. The TUI has the equivalent combined menu action and
   a disabled status entry when there are no updates. CLI: `oudedetai --update`.
2. With all three available, update OD alone and restart into the new binary.
   Check that the configured installation is retained and the old process does
   not continue updating Runtime or Logos. Keep the current config path on restart.
3. On first run with a missing/different `last_verified_od_version`, verify
   dependencies, runtime links, required registry settings, fonts, printing,
   and ICU files. Existing renderer, font smoothing, and font replacements must
   be preserved. Logos must not be reinstalled by verification.
4. Confirm both config copies record the OD version only after successful
   verification. Reopen OD: successful verification must not repeat. Interrupt
   or fail a required step: it must remain pending and retry on the next run;
   Runtime and Logos updates must be paused until it succeeds.
5. After verification, use **Update** again: Runtime completes before Logos.
   Fail the runtime update and confirm Logos is left pending.
6. From either stable or testing, offer a newer testing build and clearly warn
   that it is a pre-release. Prefer a newer stable release when one is available.
   An older stable release must not downgrade a newer testing build. Promotion
   of the installed testing release to stable should be recognised.
7. With a custom runtime, warn before replacing it. Decline replacement and
   confirm a separately approved Logos update can still proceed. Accept and
   confirm selection of the recommended release, preferring its bundle.
8. Explicit AppImage selections follow AppImage updates. A default recommendation
   that fell back to an AppImage must move to a bundle when the same/newer release
   provides one. Legacy CLI update options remain available; `--update-runtime`
   is an alias for `--update-latest-appimage`.

Desktop execution, self-replacement/restart, dependency elevation, and real Logos
launch/indexing should be tested on a disposable installation before release.
