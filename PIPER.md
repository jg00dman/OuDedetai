# Piper Read Aloud beta

This opt-in feature needs an OpenSAPI-enabled Wine AppImage and an existing
working 64-bit Logos/.NET installation. It does not install .NET or replace Wine.
Keep a backup of the prefix when testing a new Wine runtime.

Choose **Install Piper** in the GUI's App actions or the TUI Utilities menu,
or run `oudedetai --install-piper`. With Logos closed, this downloads a pinned,
SHA-256-verified prebuilt backend (about 145 MB) to this installation's
`data/opensapi/`, including its Python runtime, Piper 1.8.0, Waitress 3.0.2,
licence notices and the en_US-ljspeech-medium ONNX voice/configuration.
No system Python, compiler, distro Piper package or pip installation is needed.
Currently the backend package targets x86-64 Linux with glibc 2.35 or newer.
The corresponding sources and licence provenance are available at:
https://github.com/jg00dman/opensapi/releases/tag/piper-backend-41388556427-1

The model repository declares MIT, and its individual model card identifies a
public-domain LJ Speech dataset and training from scratch. These declarations
are preserved with the package; they do not apply to arbitrary other voices.
Piper and our service are GPL-3.0-or-later and remain separate from OuDedetai.

**Configure Piper** / `--configure-piper` instead selects an already extracted
backend executable and an ONNX model with its matching `.onnx.json` file.
Both paths register the voice as the default in the selected Logos prefix and
set builtin SAPI there. They require an OpenSAPI AppImage, not an arbitrary Wine.
The feature defaults to disabled and is persisted per OuDedetai configuration.

**Start Piper**, **Stop Piper**, and **Disable Piper** also have CLI equivalents
`--start-piper`, `--stop-piper`, `--disable-piper`. With the feature enabled, Logos
launch waits for backend readiness. A backend failure produces a diagnostic but
still permits Logos to launch without speech. The process monitor keeps Piper
running past the Logos splash/launcher exit and stops it after the main app exits.

Only a process created by this installation, verified by PID, creation time and
instance token, is stopped. An already running compatible service is reused and
left running if externally owned. Services with a different voice are rejected.
The endpoint is fixed at 127.0.0.1:5000. Logs and process ownership records live
in `data/opensapi/`. Disabling stops automatic management; it does not uninstall
the model or remove previously registered voice/default entries from the prefix.

The updated Wine transport is a separate candidate: 50 ms cancellation polling,
3-second connection, 5-second send and 65-second total request deadlines. It
requires Content-Length WAV responses, as supplied by this backend and Piper's
HTTP server. No proxy, redirects, downloads or remote network endpoints are used.

Before general release, desktop-test: missing/stale voice registration; starting
Logos with Piper absent; killing Piper during Read Aloud; restarting it and
retrying; a missing/corrupt model; backend errors and slow responses. Check that
Logos remains usable and that stop/jump controls respond during an active request.
Automated transport/PCM and lifecycle tests do not replace those desktop checks.

Validation: the first integration build passed all 96 tests (16 existing skips)
in GitHub Actions and produced x86-64 and ARM OuDedetai executables. Local full
suite has a pre-existing filesystem-size assertion failure; the 19 new tests
pass locally and in CI. Actual packaged-server readiness, ownership-safe external
reuse, stop and restart were also tested independently of mocks and Logos.

Managed OpenSAPI launches use AppImage extraction mode, including Wine version
checks and wineserver calls, so the feature does not depend on FUSE availability.
Stop an older manually started Piper HTTP server before switching to managed
startup; compatible OpenSAPI services advertise /health and can be safely reused.
