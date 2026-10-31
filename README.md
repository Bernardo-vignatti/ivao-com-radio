# COM — your iPhone as a radio panel for IVAO

[![License: MIT](https://img.shields.io/badge/license-MIT-FFA524.svg)](LICENSE)
![Windows](https://img.shields.io/badge/PC-Windows%2010%2F11-293134.svg)
![MSFS](https://img.shields.io/badge/sim-MSFS%202020-293134.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-293134.svg)

**[Leia em português](README.pt-BR.md)**

COM turns an iPhone into a panel-mounted comm radio for flying on the IVAO
network with Microsoft Flight Simulator: a gas-discharge style display with
active and standby frequencies, a swap key, a dual tuning knob, a big
push-to-talk button, and the list of ATC online around you, sorted by
distance. Tap a controller and their frequency goes to standby, just like a
real radio.

Audio and microphone stay on the PC. The phone is only the panel.

<p align="center">
  <img src="docs/radio.png" width="250" alt="Radio screen while someone is transmitting: green frame, seven-segment display with active 122.800 and standby 118.700, tuning knob, green PTT button, list of nearby ATC">
  &nbsp;
  <img src="docs/waiting.png" width="250" alt="Waiting screen shown when the PC app is closed: the radio display switched off">
</p>
<p align="center">
  <img src="docs/pc-window.png" width="600" alt="PC app dashboard with status cards, a mirror of the radio, the IVAO audio level chart and nearby ATC">
</p>

## Features

- **Push-to-talk** from the phone, with a dead-man switch: if Wi-Fi drops while
  you hold the button, the PC releases the key in 700 ms, so you never get
  stuck transmitting.
- **Active and standby frequencies** read from and written to the simulator.
  Swap like a real radio. Tune standby with the dual knob (outer ring MHz,
  inner knob kHz; tap the inner knob for 8.33 kHz channels) or type it on the
  keypad.
- **Nearby ATC** from IVAO's public data, sorted by distance from your
  aircraft. Tap one to load it into standby.
- **Receive indicator.** The whole screen frame turns green when someone is
  talking and red when you are, readable from the corner of your eye with the
  phone in a mount.
- **Real app feel.** Add it to the home screen once; it opens full screen and
  shows "Waiting for the PC" until you start COM on the computer, then the
  radio appears on its own.
- **No audio setup.** No virtual cables and no routing: COM watches IVAO's
  volume in the Windows mixer to know when someone is speaking.
- **PC dashboard in the system tray.** A window shows each part's status, a
  live audio chart for tuning the squelch, the PTT key and every setting.
  Closing it keeps COM running in the tray; quit from the tray menu.
- **Updates itself.** When a new version is out on GitHub, the window says so;
  one click downloads it, checks it, installs it and reopens COM.

## How it works

IVAO's pilot client has no API, so COM never talks to IVAO itself. It drives
the PC from the outside, the same way joystick PTT add-ons do:

| What | How |
|---|---|
| PTT | Presses the key you already set as PTT in IVAO, through Windows `SendInput` with scancodes (works with the sim fullscreen) |
| Frequencies | Reads and writes the sim's COM radio through SimConnect; IVAO follows the sim's radio |
| Receive light | Reads IVAO's peak level from the Windows audio mixer |
| ATC list | IVAO's public Whazzup API, every 15 s |

```
iPhone (home-screen web app, cached by a service worker)
   │  WebSocket over HTTPS on your Wi-Fi, with a local certificate
   ▼
COM Radio.exe ── one state, broadcast 10× per second
   ├── ptt.py       SendInput with scancodes
   ├── sim.py       SimConnect: reads radio and position, writes standby and swap
   ├── audio.py     IVAO's peak in the Windows mixer, with squelch
   ├── whazzup.py   IVAO public API, distance with haversine
   └── certs.py     local certificate authority, so Safari allows HTTPS
```

Safari only keeps a web app working offline over HTTPS, so COM creates its own
small certificate authority on your PC. You trust it on the iPhone once.

## Requirements

- Windows 10 or 11 with Microsoft Flight Simulator 2020
- IVAO's pilot client, with a PTT key set
- An iPhone on the same Wi-Fi as the PC

## Quick start

1. Download `COM-Radio-Setup-<version>.exe` from the
   [latest release](../../releases/latest) and run it. It installs COM in
   Program Files, creates the shortcuts, allows COM on **private** networks in
   Windows Firewall (otherwise the iPhone can't reach the PC), and installs
   Microsoft's WebView2 if it is missing. Uninstall it from Windows Settings
   like any other app.
   - The installer is not code-signed, so Windows SmartScreen may warn you the
     first time: click **More info › Run anyway**.
   - Your Wi-Fi must be set as a **private** network in Windows.
2. Open **COM Radio** from the Start menu.
3. **Set your PTT key:** on the **Tecla PTT** page, click **Mudar tecla**
   (change key), then press the key or mouse button you use for PTT in IVAO.
   COM recognizes it and saves it; no need to know its name.
4. **On the iPhone, once:** on the **iPhone** page, point the camera at the QR
   code (or open the `http://…:8080` address it shows in Safari) and follow
   the four steps on the page:
   1. download the certificate;
   2. install it in **Settings › Profile Downloaded**;
   3. turn it on in **Settings › General › About › Certificate Trust
      Settings**;
   4. when the page shows a green button, open the radio and use
      **Share › Add to Home Screen**.

From then on: open IVAO, open COM, tap the COM icon on the phone, fly.

The certificate lives in `%APPDATA%\COM Radio\certs`. Keep that folder: if it
is deleted, the PC creates a new one and the iPhone has to repeat step 4. When
uninstalling, COM asks before deleting it.

Coming from the old zip version? Copy the old `config.json` to
`%APPDATA%\COM Radio\` before opening the new one, or just set the PTT key
again.

## Configuration

Everything can be changed in the window: the **Áudio** page has the squelch
sliders over a live chart and finds IVAO's program for you, and
**Configurações** (settings) has the rest, including starting with Windows.
It is all saved to `%APPDATA%\COM Radio\config.json`, which you can also edit
by hand (with COM closed).

| Key | Default | What it does |
|---|---|---|
| `ptt_key` | `leftctrl` | Key pressed for PTT. Easiest to set with the **Mudar tecla** button in the window. By hand: letters, digits, `f1`–`f24`, numpad keys, modifiers (`leftctrl`, `rightalt`…), or mouse buttons `mouseback`, `mouseforward`, `mousemiddle`. Full list: `SCANCODES` in `app/ptt.py` |
| `ptt_deadman_ms` | `700` | Releases PTT if the phone goes silent this long |
| `audio_process` | `["ivao", "altitude"]` | Any part of the path of the program whose volume means "someone is talking" |
| `squelch_open` / `squelch_close` | `0.03` / `0.01` | Level that turns the receive light on / off |
| `squelch_hang_ms` | `350` | Keeps the light on through short pauses in speech |
| `whazzup_radius_nm` | `250` | How far to look for ATC |
| `whazzup_max_stations` | `12` | How many controllers to list |
| `whazzup_interval_s` | `15` | How often to ask IVAO for the ATC list (at least 15) |
| `port` / `setup_port` | `8443` / `8080` | Radio (HTTPS) and install page (HTTP) |
| `sim_enabled`, `audio_enabled`, `whazzup_enabled` | `true` | Turn a part off |
| `tray_on_close` | `true` | Closing the window keeps COM running in the tray |

Tips for the PTT key:

- If left Ctrl does something else in your sim, `f13` is a good choice: no
  program uses it.
- With `mouseback`, whatever window has focus also gets a real "back" click.
  Inside the sim that does nothing, but a browser in front goes back a page on
  every transmission.

## Safety

A PTT stuck on would block the frequency for everyone, so releasing the key is
covered five ways: the phone sends a heartbeat every 200 ms while you hold the
button and the PC lets go after 700 ms without one; the phone also releases
when the app goes to the background, when it loses focus, when the page
closes, and the PC releases on disconnect and on shutdown. With two phones
open, only the first to press controls PTT until it lets go.

## Troubleshooting

**PTT doesn't transmit.** Click **Testar tecla** (test key) on the PTT page.
If it says the key was sent but IVAO stays silent, the key doesn't match
IVAO's PTT setting. Error 5
means IVAO or the sim runs as administrator and COM doesn't: run COM as
administrator too. With the sim in exclusive fullscreen, try borderless
windowed.

**"MSFS closed" with the sim open.** Load a flight until you are in the
cockpit; in the main menu the sim doesn't answer radio requests.

**The frequency doesn't change.** Check avionics power: the sim ignores radio
writes with the avionics off. `py app/server.py --test-sim` writes a frequency,
checks it took, swaps, and puts everything back.

**"Open IVAO to get the receive light" with IVAO open.** On the **Áudio**
page, click **Procurar programas com som** (find programs playing sound) while
someone talks on frequency, and pick the right one with **Usar este** (use
this).

**The receive light flickers or never turns on.** On the **Áudio** page, watch
the chart when someone talks and drag the open line a bit below the voice and
the close line around half. The level follows IVAO's volume in Windows.

**Empty ATC list.** Increase the search radius in **Configurações**.

**The window doesn't open.** COM may already be running in the tray (opening
it again just shows the window). Otherwise install Microsoft's "Edge WebView2
Runtime". The log is in `%APPDATA%\COM Radio\com-radio.log`.

## Running from source

Needs Python 3.12 or newer on Windows.

```bash
py -m pip install -r requirements.txt
py app/gui.py
```

`py app/server.py` runs the same server in a terminal, plus diagnostic modes:

| Command | What it does |
|---|---|
| `py app/server.py --doctor` | Checks PTT, audio, IVAO data and the sim, and says what is missing. **Presses the PTT key for real** |
| `py app/server.py --test-ptt` | Presses and releases the PTT key and confirms Windows saw it |
| `py app/server.py --test-sim` | Writes to the sim's COM1 standby, swaps, and restores everything |
| `py app/server.py --list-audio` | Lists programs playing sound, to find IVAO's |
| `py app/server.py --meter` | Live receive level, to tune the squelch |
| `py app/server.py --fake-sim` | Runs with a fake simulator, to work on the interface |

`py app/gui.py --fake-sim` opens the window with the fake simulator.

`build.bat` builds the app with PyInstaller and then the installer
`dist\COM-Radio-Setup-<version>.exe` with [Inno Setup](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`).

Both interfaces are plain HTML, CSS and JavaScript with no build step: the
phone radio in `app/static/`, the PC window in `app/desktop/` (shown by
[pywebview](https://pywebview.flowrl.com/), talking to Python through its
bridge, never over the network). The type is [B612](https://b612-font.com/),
designed by Airbus for cockpit displays; the phone's seven-segment digits are
drawn in SVG.

## Disclaimer

COM is an independent project, not affiliated with or endorsed by IVAO. It
doesn't connect to IVAO's servers or touch its protocol: it only presses a key,
talks to the simulator through SimConnect, and reads public data.

## License

[MIT](LICENSE) © 2026 Bernardo Vignatti
