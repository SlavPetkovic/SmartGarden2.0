# Pi setup

Getting from a logged-in Raspberry Pi to Claude Code building layers on its own.
Run these once. `docs/autonomous-build.md` takes over afterwards.

Target: Raspberry Pi 5, 8 GB, Pi OS Trixie, 256 GB NVMe on the M.2 HAT.

---

## 1. Get a shell

Three ways in, best first:

- **SSH** — `ssh slavp@naturalis-pi.local` from the Windows box. Best for real
  work: fast, scriptable, survives a closed laptop if you run under `tmux`.
- **Raspberry Pi Connect → Remote Shell** — a terminal in the browser at
  <https://connect.raspberrypi.com>. No port forwarding, works from anywhere.
  Good for setup and for checking in from a phone.
- **Raspberry Pi Connect → Screen Sharing** — the full desktop. Fine for looking
  at the dashboard in a browser on the Pi; a poor place to run a long build.

If SSH is not enabled yet, turn it on from Connect's remote shell:
`sudo raspi-config nonint do_ssh 0`

Run long builds under `tmux` so closing the terminal does not kill them:

```bash
sudo apt install -y tmux
tmux new -s garden        # detach with Ctrl-b then d, return with: tmux attach -t garden
```

---

## 2. Enable the bus and check the hardware

```bash
sudo raspi-config nonint do_i2c 0     # enable I2C
sudo apt install -y i2c-tools git sqlite3
sudo reboot
```

After the reboot:

```bash
i2cdetect -y 1
```

Expected addresses, per `config/sensors.toml`:

| Address | Device | Notes |
|---|---|---|
| `0x77` | BME680 | some breakouts sit at `0x76` — if you see that instead, it is a config fix, not a fault |
| `0x10` | VEML7700 | |
| `0x36` | Seesaw soil | `0x36`–`0x39` available; beyond four you need the TCA9548A |

Whatever answers here is the truth. Not all three are wired yet, and that is a
supported state — `config/sensors.toml` describes the intended topology, and a
configured sensor that does not answer is reported offline rather than treated
as an error. Note which ones responded; you will want it when reviewing layer 03.

---

## 3. Project and virtualenv

The build needs **git**, but not **GitHub**. Branches, commits and the clean-tree
check in `autobuild.sh` are all local operations; `git push` is denied outright in
`.claude/settings.json`. A repository with no remote works exactly the same.

Copy the project from the Windows machine — from PowerShell there, with SSH
enabled on the Pi:

```powershell
scp -r "C:\Users\slavp\OneDrive\PROJECTS\SmartGarden" slavp@naturalis-pi.local:~/SmartGarden
```

Then on the Pi, make it a local repository (do **not** run `init-repo.sh` — it
requires a remote and pushes to it):

```bash
cd ~/SmartGarden
git init -b main
git add -A
git commit -m "Layer 1: foundation, plus autonomous build kit"
```

With no remote, the Pi is the only copy of everything the autonomous runs
produce. Push a snapshot back to the synced Windows folder now and then:

```bash
git bundle create /tmp/smartgarden.bundle --all
scp /tmp/smartgarden.bundle slavp@naturalis:/c/Users/slavp/OneDrive/PROJECTS/
```

Then the virtualenv:

```bash
cd ~/SmartGarden
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[pi,web,dev]"
```

`PLAT-1` requires a project-local virtualenv; nothing goes in system Python. The
`pi` extra pulls `gpiozero` and `lgpio` — **not** `RPi.GPIO`, which cannot address
the Pi 5's GPIO behind the RP1 south bridge.

Confirm layer 01 still works on the Pi:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t .
PYTHONPATH=src .venv/bin/python -m smartgarden.cli config check
```

---

## 4. Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude --version
```

Pi OS Trixie is Debian 13 and the Pi 5 is ARM64 with 8 GB, all comfortably
inside the supported set (Debian 10+, ARM64, 4 GB+). Requires a Pro, Max, Team
or Enterprise account.

First run authenticates through a browser. On a headless Pi, `claude` prints a
URL — open it on your laptop and paste the code back:

```bash
cd ~/SmartGarden
claude
```

Put the permission envelope in place — it ships in `setup/` because the folder
that syncs this repo cannot write into `.claude/` directly:

```bash
mkdir -p .claude/commands
cp setup/claude/settings.json          .claude/settings.json
cp setup/claude/commands/next-layer.md .claude/commands/next-layer.md
```

`CLAUDE.md`, `.claude/settings.json` and `docs/` then load automatically. Check
the rules resolved as intended before trusting them with an unattended run:

```bash
claude doctor
```

---

## 5. Build

Interactive, one layer at a time, watching:

```bash
cd ~/SmartGarden
claude
> /next-layer 02
```

Unattended:

```bash
scripts/autobuild.sh 02
```

Order is `02 → 03 → 04a → 05 → 06`, then the soak, then `04b`. The reasoning is
in `docs/autonomous-build.md` §1. Each run lands on its own `auto/layer-NN`
branch; you merge.

To leave one running overnight:

```bash
tmux new -s build -d 'scripts/autobuild.sh 03 8 2>&1 | tee .autobuild/run-03.log'
```

---

## 6. Nightly soak report

For stage B — the days of logged readings that set the moisture thresholds.
Wants layer 04a running and `automation_enabled = false`.

`scripts/soak-report.sh` writes a dated summary to `.autobuild/soak/`. As a user
timer, so it needs no root:

```bash
mkdir -p ~/.config/systemd/user
```

`~/.config/systemd/user/soak-report.service`:

```ini
[Unit]
Description=SmartGarden nightly soak report

[Service]
Type=oneshot
WorkingDirectory=%h/SmartGarden
ExecStart=%h/SmartGarden/scripts/soak-report.sh
```

`~/.config/systemd/user/soak-report.timer`:

```ini
[Unit]
Description=Nightly SmartGarden soak report

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now soak-report.timer
loginctl enable-linger "$USER"      # so it runs when you are not logged in
```

---

## 7. Reaching the dashboard

Once layer 05 is running, the API and PWA serve on port 8000. The blueprint
makes Tailscale the access boundary — there is no login, so do not expose the
port to your LAN, let alone the internet:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Then the dashboard is at `http://<pi-tailscale-name>:8000` from any device on
your tailnet, phone included. Install it as a PWA from there.

---

## 8. When something is wrong

```bash
PYTHONPATH=src .venv/bin/python -m smartgarden.cli doctor   # what answered on the bus
journalctl --user -u soak-report -n 50                      # timer output
tail -n 40 .autobuild/gate-tests.log                        # last failed gate
cat .autobuild/BLOCKED-*.md                                 # why a build stopped
```

A build that stopped and explained itself is working correctly. See
`docs/autonomous-build.md` §6.
