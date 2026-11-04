# Akousousin shared speech working-branch test

Extract the artifact, run `sha256sum --check SHA256SUMS`, then:

```
chmod +x oudedetai-x86_64
DIALOG=tk ./oudedetai-x86_64
```

Stop the older Piper service before testing. Select **Enable speech** to install
and configure the latest compatible Akousousin beta. OuDedetai verifies the release
checksum and installs `~/.local/share/Akousousin/Akousousin-x86_64.AppImage`. It invokes
Akousousin to register speech in the configured Logos prefix. The bundled LJSpeech
starter voice is available immediately on a fresh setup. Other voices and
preferences are managed through **Configure speech…**, including model import and
licence-reviewed downloads.

Click **Run Logos**, test Read Aloud, then close Logos. Akousousin owns session
tracking: it stops/exits when its last automatic session ends, but preserves an
independent/manual instance or another application's session. Closing the control
panel leaves speech running. Tray Quit explicitly stops Piper and exits Akousousin.

OuDedetai stores only `speech_enabled` in its existing configuration. Everything
else belongs to Akousousin: config in `~/.config/Akousousin`, voices/AppImage in
`~/.local/share/Akousousin`, logs in `~/.local/state/Akousousin`, temporary service data
in the private user runtime directory. XDG overrides are respected. Previous
installation-specific `data/akousousin` settings are not copied or deleted.

Speech errors do not prevent Logos from starting. This is an x86-64 Linux test
build; Wine is not replaced. Keep a backup of the prefix for beta testing.

The existing directory-size tests have portable-fixture corrections maintained
separately on `codex/akousousin-test-fixtures`. Branch CI overlays those two test
fixtures to run the full suite; they are not part of the speech integration diff.
No PR or OuDedetai release has been created.
