# Samsung Galaxy Book6 Pro — Optimisation Arch Linux

**Matériel :** Samsung Galaxy Book6 Pro 16" (NP960XJG) — Intel Core Ultra X7 358H (Panther Lake), Intel Arc B390, 32GB LPDDR5X, 1TB NVMe Samsung  
**OS :** Arch Linux, kernel 7.x, systemd-boot (UKI), BTRFS chiffré (LUKS), Wayland/KDE

---

## 1. Paramètres kernel (cmdline UKI)

Éditer `/etc/kernel/cmdline`, puis rebuilder avec `sudo mkinitcpio -P`.

```
xe.enable_psr=0 xe.enable_psr2_sel_fetch=0 xe.enable_panel_replay=0 fred=on
```

| Paramètre | Effet |
|---|---|
| `xe.enable_psr=0` | Désactive Panel Self Refresh — corrige les freezes display |
| `xe.enable_psr2_sel_fetch=0` | Désactive Selective Fetch — corrige la corruption au retour du fullscreen |
| `xe.enable_panel_replay=0` | Désactive Panel Replay — complète le fix display |
| `fred=on` | Active FRED (Flexible Return and Event Delivery) — meilleure gestion des interruptions sur PTL |

> **Note :** PSR/PSR2/Panel Replay sont des features d'économie d'énergie qui causent des bugs sur le driver `xe` avec le Book6 Pro. Ils seront à réactiver progressivement sur les kernels futurs.

> **Note :** FRED est désactivé par défaut sur kernel 7.0 mais activable manuellement. Il sera actif par défaut à partir de kernel 7.1.

---

## 2. Display — Driver xe

Le GPU Arc B390 utilise le driver `xe` (pas `i915`). Plusieurs paramètres sont à désactiver pour éviter les freezes et corruptions visuelles (voir section 1).

Vérifier l'état après reboot :
```bash
cat /sys/module/xe/parameters/enable_psr         # doit être 0
cat /sys/module/xe/parameters/enable_psr2_sel_fetch  # doit être N
cat /sys/module/xe/parameters/enable_panel_replay    # doit être 0
```

---

## 3. Scheduler — scx_lavd

Installer et activer le scheduler `scx_lavd`, optimisé pour les CPU hybrides P/E-cores.

```bash
sudo pacman -S scx-scheds scx-tools
sudo systemctl enable --now scx_loader
```

Créer `/etc/scx_loader.toml` :
```toml
default_sched = "scx_lavd"
default_mode = "Auto"
```

```bash
sudo systemctl restart scx_loader
cat /sys/kernel/sched_ext/state  # doit afficher "enabled"
```

Le mode `Auto` bascule automatiquement entre powersave et performance selon la charge — idéal pour usage laptop.

---

## 4. Autonomie — Paramètres système

### 4.1 Wi-Fi power save

Désactiver le power save Wi-Fi qui cause des `missed beacons` et des microcoupures réseau.

Créer `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` :
```ini
[connection]
wifi.powersave = 2
```
```bash
sudo systemctl restart NetworkManager
```

### 4.2 PCI runtime power management

Créer `/etc/udev/rules.d/99-pci-powersave.rules` :
```
SUBSYSTEM=="pci", ATTR{power/control}="auto"
```

### 4.3 Charge threshold batterie

La batterie est accessible via `BAT1` (pas `BAT0`). KDE Powerdevil gère déjà le threshold à 90%. Pour le rendre indépendant de KDE, créer `/etc/udev/rules.d/99-battery-threshold.rules` :
```
SUBSYSTEM=="power_supply", KERNEL=="BAT1", ATTR{charge_control_end_threshold}="80"
```

### 4.4 Energy Performance Bias

```bash
# Appliquer à chaud
echo 12 | sudo tee /sys/devices/system/cpu/cpu*/power/energy_perf_bias
```

Persister via `/etc/tmpfiles.d/epb.conf` :
```
w /sys/devices/system/cpu/cpu0/power/energy_perf_bias - - - - 12
w /sys/devices/system/cpu/cpu1/power/energy_perf_bias - - - - 12
# ... répéter pour cpu0 à cpu15
```

### 4.5 Paramètres mémoire

Créer `/etc/sysctl.d/99-memory.conf` :
```ini
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
```
```bash
sudo sysctl -p /etc/sysctl.d/99-memory.conf
```

### 4.6 Platform profile automatique

Créer `/etc/udev/rules.d/99-platform-profile.rules` :
```
SUBSYSTEM=="power_supply", KERNEL=="BAT1", ATTR{status}=="Discharging", RUN+="/bin/sh -c 'echo low-power > /sys/firmware/acpi/platform_profile'"
SUBSYSTEM=="power_supply", KERNEL=="BAT1", ATTR{status}=="Charging", RUN+="/bin/sh -c 'echo balanced > /sys/firmware/acpi/platform_profile'"
```

---

## 5. Audio — Firmware CS35L57

Le Book6 Pro utilise 4 amplis Cirrus Logic CS35L57 (2 woofers + 2 tweeters) via SoundWire. Le firmware de tuning Samsung n'est pas inclus dans `linux-firmware` et doit être extrait depuis Windows.

### 5.1 Extraction depuis Windows

Monter la partition Windows (NTFS, généralement `nvme0n1p3`) :
```bash
sudo mkdir -p /mnt/win
sudo mount -t ntfs3 /dev/nvme0n1p3 /mnt/win -o ro
```

Les fichiers se trouvent dans :
```
/mnt/win/Windows/System32/DriverStore/FileRepository/xucsmeext_c1de.inf_amd64_*/
```

### 5.2 Copie des fichiers

SSID du système : `144dc1de`  
Adresses SoundWire → rôle → fichier source :

| Adresse SDW | Rôle | Fichier source |
|---|---|---|
| `sdw:0:1:01fa:3557:01:0` → `l1u0` | Left Woofer | `b2_dflt_SS0_C1DE_LW_l1u0.bin` |
| `sdw:0:1:01fa:3557:01:1` → `l1u1` | Left Tweeter | `b2_dflt_SS0_C1DE_LT_l1u1.bin` |
| `sdw:0:2:01fa:3557:01:2` → `l2u2` | Right Woofer | `b2_dflt_SS0_C1DE_RW_l2u2.bin` |
| `sdw:0:2:01fa:3557:01:3` → `l2u3` | Right Tweeter | `b2_dflt_SS0_C1DE_RT_l2u3.bin` |

```bash
SRC="/mnt/win/Windows/System32/DriverStore/FileRepository/xucsmeext_c1de.inf_amd64_d84ea07a11fd8e23"
DST="/lib/firmware/cirrus"

# Firmware DSP (.wmfw) — partagé par les 4 amplis
sudo cp "$SRC/fw/35L56/4.7.0/dflt/b2_dflt_35l56_4.7.0.wmfw" \
    "$DST/cs35l57-b2-dsp1-misc-144dc1de.wmfw"

# Tunings (.bin) — un par ampli
sudo cp "$SRC/tn/35L57/C1DE/dflt/b2_dflt_SS0_C1DE_LW_l1u0.bin" \
    "$DST/cs35l57-b2-dsp1-misc-144dc1de-l1u0.bin"
sudo cp "$SRC/tn/35L57/C1DE/dflt/b2_dflt_SS0_C1DE_LT_l1u1.bin" \
    "$DST/cs35l57-b2-dsp1-misc-144dc1de-l1u1.bin"
sudo cp "$SRC/tn/35L57/C1DE/dflt/b2_dflt_SS0_C1DE_RW_l2u2.bin" \
    "$DST/cs35l57-b2-dsp1-misc-144dc1de-l2u2.bin"
sudo cp "$SRC/tn/35L57/C1DE/dflt/b2_dflt_SS0_C1DE_RT_l2u3.bin" \
    "$DST/cs35l57-b2-dsp1-misc-144dc1de-l2u3.bin"
```

### 5.3 Vérification après reboot

```bash
sudo dmesg | grep -i "cs35l\|calibr\|tuning"
# Attendu : "Calibration applied" x4, plus de "FIRMWARE_MISSING"
```

---

## 6. BTRFS — Swap isolé

Le swapfile doit être dans un subvolume séparé `@swap` pour que snapper ne tente pas de le snapshoter (ce qui causerait des erreurs).

### 6.1 Créer le subvolume et le swapfile

```bash
sudo mount -o subvol=/ /dev/mapper/root /mnt
sudo btrfs subvolume create /mnt/@swap
sudo btrfs filesystem mkswapfile --size 32G /mnt/@swap/swapfile
sudo umount /mnt
```

### 6.2 fstab

Ajouter dans `/etc/fstab` (avant la ligne swapfile) :
```
UUID=<uuid-btrfs>  /swap  btrfs  rw,noatime,ssd,space_cache=v2,subvol=/@swap  0 0
```

Et la ligne swap :
```
/swap/swapfile  none  swap  defaults  0 0
```

```bash
sudo mkdir -p /swap
sudo mount -a
sudo swapon /swap/swapfile
```

---

## 7. Firmware — Vérification et mises à jour

```bash
sudo fwupdmgr refresh
sudo fwupdmgr get-updates
sudo fwupdmgr update  # si des mises à jour sont disponibles
```

Le BIOS se met à jour via capsule UEFI (fwupd). Pas besoin de Windows pour les mises à jour firmware.

---

## 8. Points d'attention futurs

### Kernel 7.1
- FRED sera actif par défaut (retirer `fred=on` du cmdline)
- Meilleur support `pc10` (Package C10) sur Panther Lake → gain autonomie significatif

### PSR/Panel Replay
- Tester la réactivation progressive une fois les drivers `xe` stabilisés :
  1. Retirer `xe.enable_psr2_sel_fetch=0` en premier
  2. Puis `xe.enable_panel_replay=0`
  3. Puis `xe.enable_psr=0` en dernier

### linux-firmware
- Surveiller l'ajout de firmware officiel Samsung CS35L57 dans linux-firmware upstream — à terme les fichiers extraits de Windows ne seront plus nécessaires.

---

## 9. Récapitulatif des fichiers modifiés

| Fichier | Contenu |
|---|---|
| `/etc/kernel/cmdline` | Paramètres kernel (PSR, FRED) |
| `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` | Wi-Fi power save désactivé |
| `/etc/udev/rules.d/99-pci-powersave.rules` | PCI runtime PM auto |
| `/etc/udev/rules.d/99-battery-threshold.rules` | Charge threshold 80% |
| `/etc/udev/rules.d/99-platform-profile.rules` | Profile auto sur batterie |
| `/etc/tmpfiles.d/epb.conf` | Energy Performance Bias |
| `/etc/sysctl.d/99-memory.conf` | Paramètres mémoire |
| `/etc/scx_loader.toml` | Scheduler scx_lavd |
| `/etc/fstab` | Subvolume @swap |
| `/lib/firmware/cirrus/cs35l57-b2-*` | Firmware audio CS35L57 |
