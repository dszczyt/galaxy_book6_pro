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

## 5. Performances stockage et mémoire

### 5.1 Scheduler NVMe — mq-deadline

Créer `/etc/udev/rules.d/60-nvme-scheduler.rules` :
```
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="mq-deadline"
```
```bash
sudo udevadm trigger --action=change --subsystem-match=block
cat /sys/block/nvme0n1/queue/scheduler  # doit afficher [mq-deadline]
```

### 5.2 noatime sur les montages BTRFS

Dans `/etc/fstab`, remplacer `relatime` par `noatime` sur les subvolumes `@` et `@home`. Garder `relatime` sur les montages swap, logs et pkg.

```bash
sudo systemctl daemon-reload
sudo mount -o remount /
sudo mount -o remount /home
```

### 5.3 fstrim périodique

```bash
sudo systemctl enable --now fstrim.timer
```

### 5.4 zram — swap compressé en RAM

Créer `/etc/systemd/zram-generator.conf` :
```ini
[zram0]
compression-algorithm = zstd
zram-size = ram / 2
```
```bash
sudo systemctl restart systemd-zram-setup@zram0
zramctl  # doit afficher ~15.4GB
```

---

## 6. GPU Arc B390 — Optimisations avancées

### 6.1 SAGV (System Agent Voltage Gating)

Ajouter dans `/etc/kernel/cmdline` :
```
xe.enable_sagv=1
```
Puis rebuilder : `sudo mkinitcpio -P`

Active le voltage gating du System Agent Intel — économie d'énergie sur la mémoire. **Expérimental** (taint kernel).

### 6.2 VA-API — Décodage vidéo hardware

```bash
sudo pacman -S libva-utils
vainfo  # doit lister H264/HEVC/AV1 VAEntrypointVLD
```

L'Arc B390 supporte le décodage hardware de tous les codecs modernes via VA-API.

### 6.3 DVMT Pre-Allocated — FBC complet

**Problème :** Le driver `xe` affiche au boot :
```
xe: Reducing the compressed framebuffer size. This may lead to less power savings
```
FBC (Framebuffer Compression) réduit → plus de bande passante mémoire → moins d'autonomie.

**Cause :** Samsung bloque l'option DVMT Pre-Allocated dans le BIOS (menu caché). Valeur par défaut : 64MB. Insuffisant pour FBC complet sur dalle haute résolution.

**Solution : modifier la variable NVRAM `SaSetup` directement depuis Linux.**

#### Analyse du BIOS (déjà effectuée — résultats)

```bash
# Dump du flash SPI
sudo flashrom -p internal -r /tmp/bios.bin

# Extraction des modules UEFI
uefiextract /tmp/bios.bin
```

Résultats de l'analyse IFR :
- Variable : **SaSetup**
- GUID : `72C5E28C-7783-43A1-8767-FAD73FCCAFA4`
- Offset dans SaSetup : **0x05**
- Opcode IFR : NUMERIC, min=0, max=7, step=1
- Valeur actuelle : `0x02` = 64MB
- Valeur cible : `0x04` = 128MB (ou `0x07` = max)
- Offset absolu dans le flash 32MB : `0x1056725` (entrée NVAR active, next=0xffffff)
- Secteur SPI concerné : `0x1056000–0x1057000` (4KB)
- Note : la chaîne NVAR comporte 4 entrées pour SaSetup. L'entrée 1 (`0x104c55f`) contient le nom ; les entrées 2–4 sont DATA-only. Seule l'entrée 4 (`0x1056716`, next=0xffffff) est lue par le BIOS.

#### Modification depuis Linux (MTD)

Le flash SPI est accessible en écriture via `/dev/mtd0` (`flags=0xc00` = MTD_WRITEABLE).

Le script calcule **tous les offsets dynamiquement** depuis le flash live — aucune valeur hardcodée. Il suit la chaîne NVAR jusqu'à l'entrée active (`next=0xffffff`) et vérifie la structure avant d'écrire.

```bash
# Dry run (défaut) — vérifie tout, n'écrit rien
sudo python3 write_dvmt.py

# Écriture effective
sudo python3 write_dvmt.py --write
```

Script [`write_dvmt.py`](./write_dvmt.py) (dans ce repo) :

```
Logique du script :
1. Lit /dev/mtd0 en entier
2. Localise le NVAR store via CHIPSEC (getNVstore_NVAR)
3. Scanne toutes les entrées NVAR, trouve celle nommée "SaSetup"
4. Suit la chaîne next → next → ... jusqu'à next=0xffffff (entrée active)
5. Vérifie : signature NVAR présente, data_len==890, valeur courante==0x02
6. Calcule le secteur 4KB contenant le byte DVMT
7. Dry run : affiche ce qui serait fait, sort sans écrire
8. --write : efface le secteur, écrit le secteur patché, vérifie relecture

Sécurités :
- Abort si valeur inattendue (pas 0x02)
- Abort si data_len != 890 (mauvaise variable)
- Abort si entrée active introuvable
- Vérifie que le flash live correspond au dump avant d'écrire
- Exactement 1 byte changé dans le secteur (assertion)
- FAIL détecté si SPI write protection active (→ utiliser RU.efi)
```

#### Vérification après reboot

```bash
sudo dmesg | grep -i "stolen\|fbc\|framebuffer\|compressed"
# Le message "Reducing the compressed framebuffer size" ne doit plus apparaître
```

#### Statut — Toutes les tentatives échouées (protection firmware Samsung)

**Résumé : la modification est bloquée par deux protections indépendantes du firmware Insyde.**

##### Tentative 1 — Écriture directe MTD depuis Linux (`write_dvmt.py --write`)

```
ioctl(MEMERASE) → errno 5 (EIO)
```

Le driver Linux `intel_spi` refuse l'effacement. La protection SPI (PR registers + FLOCKDN) est active :
- Le BIOS configure les registres Protected Range (PRx) pour couvrir la région BIOS
- Il pose `FLOCKDN=1` (Flash Configuration Lock-Down) pour verrouiller les PRx
- Le driver MTD voit la protection hardware → refuse toute écriture

##### Tentative 2 — RU.efi (outil BIOS UEFI)

RU.efi est **incompatible avec Panther Lake** : se ferme immédiatement au lancement, quelle que soit la méthode (systemd-boot, entrée EFI directe, clé USB). Non débogable.

##### Tentative 3 — `setup_var.efi` 0.3.1 via UEFI Shell (edk2-shell)

Setup :
- `Shell.efi` (edk2-shell) + `setup_var.efi` copiés dans `/boot/EFI/SHELL/`
- `startup.nsh` au racine EFI : `setup_var.efi --reboot=auto --write_on_demand SaSetup:0x05=0x04`
- Entrée EFI `Boot0004 UEFI Shell DVMT` en premier dans BootOrder

Résultat au boot :

```
[1] SaSetup:0x5=0x02           ← lecture OK, variable trouvée
[2] Error while setting content of variable SaSetup: WRITE_PROTECTED
[3] SaSetup:0x5=0x02           ← inchangé
```

**Cause** : le BIOS Insyde appelle `VariableLock()` sur `SaSetup` pendant la phase DXE, avant l'événement ReadyToBoot. Le shell UEFI se lance après ReadyToBoot — `SetVariable` retourne `WRITE_PROTECTED` de façon permanente.

La variable est en `BOOTSERVICE_ACCESS` uniquement (invisible depuis l'OS via `/sys/firmware/efi/efivars`), mais le verrouillage s'applique dès la fin de la phase DXE, indépendamment de la visibilité runtime.

##### Pistes restantes

| Outil | Mécanisme | Disponibilité |
|---|---|---|
| **Insyde H2OUVE** (`H2OUVEFI.efi`) | Éditeur Insyde natif — peut contourner `VariableLock` via protocoles Insyde internes | Propriétaire, parfois extrait de packages BIOS OEM |
| **Intel FPT** (`FPTW64.efi`) | Écrit via Intel ME (canal séparé, bypasse les PR registers SPI) | Propriétaire, CSME System Tools Intel |
| **Programmateur SPI externe** | Accès direct hardware (CH341A + pince SOIC-8) | Matériel requis |

##### État actuel

DVMT reste à 64MB (`SaSetup[0x05]=0x02`). Le warning xe persiste :
```
xe: Reducing the compressed framebuffer size. This may lead to less power savings
```
FBC (Framebuffer Compression) fonctionne en mode dégradé. Le GPU est pleinement fonctionnel. L'impact est une légère augmentation de la bande passante mémoire en mode desktop.

---

## 8. Audio — Firmware CS35L57

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

## 9. BTRFS — Swap isolé

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

## 10. Firmware — Vérification et mises à jour

```bash
sudo fwupdmgr refresh
sudo fwupdmgr get-updates
sudo fwupdmgr update  # si des mises à jour sont disponibles
```

Le BIOS se met à jour via capsule UEFI (fwupd). Pas besoin de Windows pour les mises à jour firmware.

---

## 11. Points d'attention futurs

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

### DVMT / FBC
- DVMT bloqué à 64MB — toutes les tentatives de modification échouent (VariableLock BIOS + SPI hardware protection). Voir section 6.3.
- Pistes : Insyde H2OUVE ou Intel FPT (tous deux propriétaires).
- Si une future mise à jour BIOS Samsung expose l'option DVMT ou corrige le warning FBC, mettre à jour cette section.

---

## 12. Récapitulatif des fichiers modifiés

| Fichier | Contenu |
|---|---|
| `/etc/kernel/cmdline` | Paramètres kernel (PSR, FRED, SAGV) |
| `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` | Wi-Fi power save désactivé |
| `/etc/udev/rules.d/60-nvme-scheduler.rules` | Scheduler NVMe mq-deadline |
| `/etc/udev/rules.d/99-pci-powersave.rules` | PCI runtime PM auto |
| `/etc/udev/rules.d/99-battery-threshold.rules` | Charge threshold 80% |
| `/etc/udev/rules.d/99-platform-profile.rules` | Profile auto sur batterie |
| `/etc/tmpfiles.d/epb.conf` | Energy Performance Bias |
| `/etc/sysctl.d/99-memory.conf` | Paramètres mémoire |
| `/etc/systemd/zram-generator.conf` | zram 15.4GB zstd |
| `/etc/scx_loader.toml` | Scheduler scx_lavd |
| `/etc/fstab` | noatime + subvolume @swap |
| `/lib/firmware/cirrus/cs35l57-b2-*` | Firmware audio CS35L57 |
| NVRAM `SaSetup[0x05]` (flash SPI) | DVMT Pre-Allocated — **bloqué** (VariableLock BIOS + SPI protection) |
