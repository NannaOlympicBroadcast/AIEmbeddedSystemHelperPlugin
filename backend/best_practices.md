# Embedded Systems Best Practices Guide

This document is maintained by repository contributors. The agent reads it before executing embedded development tasks. Please add practical, field-tested advice below.

---

## File Transfer

**Preferred method: SFTP over LAN (fastest, most reliable)**

1. Confirm the development board and your PC are on the same LAN segment (ping the board's IP first).
2. Use `sftp` or `scp` — do NOT use serial (too slow, 115200 baud ≈ 11.5 KB/s) for file transfer.
3. Typical commands:
   ```bash
   # Copy a file to the board
   scp ./firmware.bin user@192.168.1.xx:/home/user/
   # Copy from the board
   scp user@192.168.1.xx:/home/user/log.txt ./
   ```
4. If the board has no Ethernet, connect via USB-OTG or set up a WiFi hotspot on the PC first.
5. For large directories, use `rsync -avz ./src/ user@board:/home/user/src/` to sync only changed files.

**When SFTP is unavailable (serial/USB only):**

Use base64 encoding:
```bash
# On PC
base64 firmware.bin > firmware.b64
# Paste content, then on board:
base64 -d firmware.b64 > firmware.bin
```

---

## WiFi Configuration

**On Armbian / Debian / Ubuntu (NetworkManager):**
```bash
nmcli dev wifi connect "SSID" password "PASSWORD"
# Verify
nmcli connection show --active
ip addr show wlan0
```

**On Raspberry Pi OS:**
```bash
sudo nmcli dev wifi connect "SSID" password "PASSWORD"
# Or edit wpa_supplicant
sudo wpa_cli -i wlan0 reconfigure
```

**Troubleshooting:**
- Always `ping 8.8.8.8` after connecting to confirm routing.
- If DHCP is stuck, run `sudo dhclient wlan0` or `sudo systemctl restart NetworkManager`.

---

## SSH Connection

1. Find the board's IP: check router DHCP table, or run `ip addr` on the board via serial.
2. Accept RSA fingerprint on first connect; subsequent connects are safe.
3. Keep an SSH config entry:
   ```
   Host radxa
     HostName 192.168.1.xx
     User rock
     IdentityFile ~/.ssh/id_ed25519
   ```
4. If SSH is refused: check `sudo systemctl status ssh` on the board.

---

## Package Management (apt)

- Always run `sudo apt update` before installing; the package list may be stale.
- Use `sudo apt install -y <pkg>` for non-interactive installation.
- Typical install times:
  - Small utilities (curl, git, vim): **30–60 s**
  - Large packages (docker, opencv, nodejs): **2–10 min**
- **Do NOT spam terminal-output polls**; use `sleep_tool` to wait, then check once.
- If install is stuck at "0% [Waiting for headers]", the mirror may be unreachable. Try:
  ```bash
  sudo sed -i 's/ports.ubuntu.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list
  sudo apt update
  ```

---

## Docker on ARM Boards

- Install Docker with the official script:
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER && newgrp docker
  ```
- ARM boards (Radxa, RPi) use `linux/arm64` images; check with `uname -m`.
- `docker build` can take **5–30 min** on ARM; use `sleep_tool(180)` then check.
- Cross-compile on x86 with `--platform linux/arm64` and push to a registry if the board is slow.

---

## Serial Communication

- Use 115200 baud as the default; higher rates may lose bytes on long cables.
- Always check which port: `ls /dev/tty*` — usually `/dev/ttyUSB0` or `/dev/ttyACM0`.
- Set correct permissions: `sudo usermod -aG dialout $USER` (log out/in to apply).
- Reset terminal corruption with `reset` or `stty sane`.
- Serial is for console access and debugging only; avoid bulk data transfer over it.

---

## Build & Compilation

- Always create an out-of-source build directory: `mkdir build && cd build && cmake ..`
- For cross-compilation, set `CC`, `CXX`, and `SYSROOT` explicitly.
- Parallel builds with `make -j$(nproc)` speed up compilation significantly.
- If `make` is slow on the board, cross-compile on PC and copy the binary via SFTP.

---

## Networking Checklist (before any remote operation)

1. `ping <board_ip>` — LAN reachable?
2. `ping 8.8.8.8` (from board) — Internet reachable?
3. `ssh user@<board_ip> whoami` — SSH works?
4. Check firewall: `sudo ufw status` / `sudo iptables -L`

---

## General SBC Workflow

1. After first boot, update the system: `sudo apt update && sudo apt upgrade -y`
2. Set timezone: `sudo timedatectl set-timezone Asia/Shanghai`
3. Enable SSH if not already: `sudo systemctl enable --now ssh`
4. Lock down root SSH: `sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config && sudo systemctl reload ssh`
5. Create a non-root user with sudo for daily work.

---

*Contributors: please add new sections using `## Title` headings and keep instructions concise and command-ready.*
