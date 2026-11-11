# sc311-linux-flash

Flash the SK hynix SC311 SATA 128GB firmware update that Dell ships as a Windows-only tool (package J5YR3, firmware 70002P10) from Linux, without pulling the drive or booting Windows.

**Use at your own risk.** Flashing SSD firmware can brick a drive. Back up first, stay on AC power, and read the script before you run it. This project is not affiliated with SK hynix or Dell.

## Scope

Tested on exactly one drive: Dell Latitude 3390 2-in-1, SK hynix SC311 SATA 128GB, firmware 70000P10 to 70002P10.

The script refuses to run unless all of these match: model string, firmware 70000P10, 250,069,680 sectors, segmented microcode download advertised for 128-block chunks, no SMART attribute at or below its threshold, and the firmware bundle SHA-256. Other SC311 capacities and hardware variants use different bundles inside the Dell package and are not supported. Use the Dell Windows tool for those.

## The firmware is not included

The firmware belongs to SK hynix and ships under the license of the Dell updater, which does not allow redistribution. Download it from Dell and extract it yourself:

1. Get the package (driver ID J5YR3, "SK Hynix Solid State Drive Firmware Update", released 2020-04-23) from https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=j5yr3
   (direct link used while testing: https://dl.dell.com/FOLDER06215544M/7/SK%20Hynix_SC311_J5YR3_ZPE.exe, SHA-256 `9185b446c1fdb0e9d7097711a438f0d145da357dc91cd58eb47250c4dc24077b`)
2. Extract it with 7z (p7zip):

       7z x -y -ox "SK Hynix_SC311_J5YR3_ZPE.exe"
       7z x -y -ores x/SNT_Dell_SC311_vE104_70002P10.exe ".rsrc/1042/FWBINARY/136"

3. `res/.rsrc/1042/FWBINARY/136` must be 1,458,688 bytes with SHA-256 `c87e68b212dd6ffba629b950efb61a29a2db5c5e627f546d2dd409e99adad417`. The script checks this and refuses anything else.

## Usage

Dry run (reads only, writes nothing):

    sudo python3 sc311_flash.py /dev/sda res/.rsrc/1042/FWBINARY/136

Flash (waits 10 seconds, stops at the first error):

    sudo python3 sc311_flash.py /dev/sda res/.rsrc/1042/FWBINARY/136 --flash --confirm=FLASH-MY-SC311

Then power cycle and check the firmware:

    sudo hdparm -I /dev/sda | grep Firmware    # 70002P10

## What it sends

Standard ATA commands through SG_IO (ATA PASS-THROUGH 16): IDENTIFY and SMART READ DATA / READ THRESHOLDS (reads only), then 23 DOWNLOAD MICROCODE commands (0x92, subcommand 03h) of up to 128 blocks (64 KB) with sequential buffer offsets (22 x 128 blocks + 1 x 33 blocks = 2,849 blocks), then STANDBY IMMEDIATE. This is the same sequence the Dell tool issues for this drive.

`hdparm --fwdownload-mode3` is not used: on this drive it picks the minimum chunk size (1 block), so it would send 2,849 single-block commands instead of 23 large ones.

The Dell tool also rewrites a small record (the PPID string) in vendor log page 0x9A after flashing. This script does not touch it; the drive firmware does not use that log.

## Result

On one Latitude 3390 2-in-1 the drive accepted all 23 commands, reported 70002P10 immediately and again after a reboot, and showed no errors in the kernel log; SMART stayed clean. Before the real flash, the command stream was replayed against an emulated drive and compared with the Dell tool, register for register and byte for byte.

## License

MIT, see LICENSE. The firmware itself is not covered by this license.
