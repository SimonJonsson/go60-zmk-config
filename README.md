# Go60 ZMK config with Swedish letters on a US layout

This is a fork of the official [MoErgo Go60 ZMK config](https://github.com/moergo-keyboards/go60-zmk-config).
The keyboard sends plain US keycodes, the host runs a US layout, and å ä ö are
typed as combos. That keeps every US symbol exactly where it is printed, avoids
dead keys, and works the same on Linux and macOS.

## What this adds to the factory layout

| Combo (press together) | Result | Firmware sends |
|---|---|---|
| `a` + `e` | å (Å with Shift) | AltGr+W |
| `u` + `a` | ä (Ä with Shift) | AltGr+Q |
| `u` + `o` | ö (Ö with Shift) | AltGr+P |
| SymbolNav layer, `5` key | € | AltGr+5 |

The combos live only on the Base layer and use a 30 ms window, set by
`SV_COMBO_TIMEOUT_MS` at the top of `config/go60.keymap`. Raise it if the
combos miss, lower it if fast rolls like "ua" in "usual" trigger ä by mistake.

Everything else is the factory default layout: Base, Keypad, SymbolNav, Magic
and Factory layers, the Magic hold-tap, Bluetooth tap-dances and the Cirque
trackpad settings.

## Host setup

Both hosts need a US layout with Swedish letters on the AltGr level. Right Alt
on the Go60 becomes that AltGr modifier, so use Left Alt for Alt shortcuts.

### Linux

Use the `altgr-intl` variant of the `us` layout. It is the standard US layout
with accented letters on AltGr and no dead keys on the base level.

Hyprland, in `~/.config/hypr/input.lua` on Omarchy:

```lua
hl.config({
  input = {
    kb_layout = "us",
    kb_variant = "altgr-intl",
  },
})
```

Other setups: `localectl set-x11-keymap us "" altgr-intl` or
`setxkbmap us altgr-intl`.

### macOS

macOS has no built-in layout with the same chords, so this repo ships one:
`host/macos/U.S. Swedish AltGr.keylayout`. It is Apple's U.S. layout with
Option+W, Option+Q, Option+P and Option+5 changed to å, ä, ö and €, plus the
usual Shift variants. Option+A, Option+O and Option+U also give å, ö and ü.

1. Copy the file into `~/Library/Keyboard Layouts/` (create the folder if it
   does not exist).
2. Log out and back in.
3. System Settings, Keyboard, Input Sources, Edit, `+`, then pick "Others" and
   add "U.S. Swedish AltGr". Select it as the active input source.

## Building the firmware

Every push runs the GitHub Actions workflow in `.github/workflows/build.yml`.
It uploads two artifacts:

- `go60.uf2`, the combined firmware for both halves.
- `go60-layout.json`, the same keymap in MoErgo Layout Editor format.

To build locally with Docker, run `./build.sh`. It builds against the `main`
branch of [moergo-sc/zmk](https://github.com/moergo-sc/zmk); pass a tag as the
first argument to pin a release.

Flash `go60.uf2` to both halves as described on the
[official Go60 support site](https://moergo.com/go60-support).

## Layout Editor JSON

`scripts/keymap_to_layout_json.py` converts `config/go60.keymap` into the JSON
that the [Go60 Layout Editor](https://my.moergo.com/go60/) imports. The keymap
stays the source of truth; the JSON is a build artifact.

```sh
python3 scripts/keymap_to_layout_json.py config/go60.keymap --conf config/go60.conf -o go60-layout.json
python3 -m unittest discover -s scripts -p 'test_*.py'
```

To import: in the Layout Editor open Settings, enable "Local Backup and
Restore", then use the Import control in the bottom left of the edit page.

What the converter understands:

- Layers, combos, macros and hold-taps become first-class editor objects.
- The Cirque listener overrides become the editor's input listener settings.
- Behaviours the editor already provides for the Go60 are recognised by shape
  and mapped to the editor's own keys instead of being duplicated: the Magic
  hold-tap, the Keypad and SymbolNav tap-dances, the `bt_0` to `bt_3`
  tap-dances with their macros, and `&sys_reset`.
- Anything else, such as tap-dances or mod-morphs you add, is passed through
  verbatim in `custom_defined_behaviors`, and unknown devicetree overrides go
  to `custom_devicetree`. The editor builds them but cannot display them.

The JSON shape was taken from a Factory Default export and the editor's own
schema. MoErgo does not guarantee the format is stable, so if an import fails
after an editor update, export a fresh layout from the editor and compare it
with `scripts/fixtures/factory_default_layout.json`.

## Resources

- [Official MoErgo Go60 Support](https://moergo.com/go60-support)
- [MoErgo Discord](https://moergo.com/discord)
- [ZMK documentation](https://zmk.dev/docs)
- [MoErgo ZMK distribution](https://github.com/moergo-sc/zmk)
