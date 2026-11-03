# OpenSAPI working-branch test

This is an x86-64 Linux build of `codex/opensapi`, based on jg00dman/OuDedetai main.
It adds only the optional speech integration; no PR or release is created.

1. Extract the build artifact, run `sha256sum --check SHA256SUMS`, then
   `chmod +x oudedetai-x86_64` and `DIALOG=tk ./oudedetai-x86_64`.
2. Stop any old Piper server. In the existing Logos installation, select
   **Enable speech**. This offers configuration and, on first use, downloads the
   newest standalone OpenSAPI release with its checksum. Its AppImage goes in
   OuDedetai's binary directory alongside Wine AppImages.
3. In the OpenSAPI panel, import an existing ONNX voice (matching JSON alongside),
   choose **Make default**, and use **Settings → Install / apply voice registration**.
   You can also review/download a voice through that panel. Models are separate
   from the current OpenSAPI beta. Existing OpenSAPI settings are copied on first
   use when available, preserving voice choices; subsequent settings are specific
   to this OuDedetai installation.
4. Close the panel without manually starting Piper. Click **Run Logos** in
   OuDedetai; it starts speech and waits for readiness before launching Logos.
   Test Read Aloud, then close Logos. The backend started by OuDedetai should stop.
5. **Configure speech…** reopens the panel. Preferences and Enable speech persist.
   Unticking Enable speech stops a backend owned by this OuDedetai session.

A compatible backend already running for this profile is reused and left running.
A different profile's backend is left alone; speech startup reports the conflict
and Logos still launches without speech. The same applies to missing voices or
backend errors. Closing the configuration panel alone does not stop speech.

The current beta is 64-bit only. Keep using the existing Wine package and prefix;
this integration neither builds nor replaces Wine. Use a backup of the prefix for
beta testing. The OpenSAPI panel provides Uninstall & restore for speech changes.
