#!/usr/bin/env python3
# sc311_flash.py - replay of the SK hynix SC311 vendor firmware download (Dell package 70002P10, bundle 136)
# usage: sc311_flash.py DEVICE BUNDLE                                  dry run: checks only, writes nothing
#        sc311_flash.py DEVICE BUNDLE --flash --confirm=FLASH-MY-SC311 [--no-wait]
import ctypes, fcntl, hashlib, os, stat, struct, sys, time

EXPECT_MODEL = "SK hynix SC311 SATA 128GB"
EXPECT_FW = "70000P10"
EXPECT_SECTORS = 250069680
EXPECT_SIZE = 1458688
EXPECT_SHA256 = "c87e68b212dd6ffba629b950efb61a29a2db5c5e627f546d2dd409e99adad417"
CHUNK = 128
SG_IO = 0x2285
FROM_DEV, TO_DEV, NONE = -3, -2, -1


class SgIoHdr(ctypes.Structure):
    _fields_ = [("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int),
                ("cmd_len", ctypes.c_ubyte), ("mx_sb_len", ctypes.c_ubyte), ("iovec_count", ctypes.c_ushort),
                ("dxfer_len", ctypes.c_uint), ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p),
                ("sbp", ctypes.c_void_p), ("timeout", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("pack_id", ctypes.c_int), ("usr_ptr", ctypes.c_void_p),
                ("status", ctypes.c_ubyte), ("masked_status", ctypes.c_ubyte), ("msg_status", ctypes.c_ubyte),
                ("sb_len_wr", ctypes.c_ubyte), ("host_status", ctypes.c_ushort), ("driver_status", ctypes.c_ushort),
                ("resid", ctypes.c_int), ("duration", ctypes.c_uint), ("info", ctypes.c_uint)]


def die(msg):
    print("ERROR: " + msg)
    sys.exit(1)


def sg(fd, cdb, direction, buf=None):
    c = (ctypes.c_ubyte * 16)(*cdb)
    sense = ctypes.create_string_buffer(32)
    h = SgIoHdr(interface_id=ord("S"), dxfer_direction=direction, cmd_len=16, mx_sb_len=32,
                dxfer_len=len(buf) if buf is not None else 0,
                dxferp=ctypes.cast(buf, ctypes.c_void_p).value if buf is not None else None,
                cmdp=ctypes.cast(c, ctypes.c_void_p).value, sbp=ctypes.cast(sense, ctypes.c_void_p).value,
                timeout=30000)
    fcntl.ioctl(fd, SG_IO, h)
    ok = h.status == 0 and h.host_status == 0 and h.driver_status == 0
    return ok, h


def read_page(fd, cdb):
    buf = ctypes.create_string_buffer(512)
    ok, h = sg(fd, cdb, FROM_DEV, buf)
    return ok, buf.raw


def identify(fd):
    ok, d = read_page(fd, [0x85, 0x08, 0x0E, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0x40, 0xEC, 0])
    if not ok:
        die("IDENTIFY failed")
    return struct.unpack("<256H", d)


def text(words):
    return b"".join(struct.pack(">H", w) for w in words).decode("ascii", "replace").strip()


def smart_bad(fd):
    smart = [0x85, 0x08, 0x0E, 0, 0xD0, 0, 1, 0, 0, 0, 0x4F, 0, 0xC2, 0x40, 0xB0, 0]
    ok, data = read_page(fd, smart)
    if not ok:
        sg(fd, [0x85, 0x06, 0x00, 0, 0xD8, 0, 0, 0, 0, 0, 0x4F, 0, 0xC2, 0x40, 0xB0, 0], NONE)
        ok, data = read_page(fd, smart)
    if not ok:
        return None
    ok, th = read_page(fd, [0x85, 0x08, 0x0E, 0, 0xD1, 0, 1, 0, 0, 0, 0x4F, 0, 0xC2, 0x40, 0xB0, 0])
    if not ok:
        return None
    thr = dict((th[i], th[i + 1]) for i in range(2, 362, 12) if th[i])
    return [(data[i], data[i + 3], thr[data[i]]) for i in range(2, 362, 12)
            if data[i] and thr.get(data[i]) and data[i + 3] <= thr[data[i]]]


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        die("usage: sc311_flash.py DEVICE BUNDLE [--flash --confirm=FLASH-MY-SC311] [--no-wait]")
    dev, bundle = args[0], args[1]
    do_flash = "--flash" in args
    confirmed = "--confirm=FLASH-MY-SC311" in args
    name = os.path.basename(dev)
    if not (name.startswith("sd") and name[2:].isalpha() and stat.S_ISBLK(os.stat(dev).st_mode)):
        die("DEVICE must be a whole SATA disk such as /dev/sda")
    data = open(bundle, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    print("bundle: %d bytes (%d blocks), sha256 %s" % (len(data), len(data) // 512, sha))
    if len(data) != EXPECT_SIZE or sha != EXPECT_SHA256:
        die("bundle does not match the expected 136 firmware bundle")
    fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    w = identify(fd)
    model, fw = text(w[27:47]), text(w[23:27])
    sectors = w[100] | w[101] << 16 | w[102] << 32 | w[103] << 48
    print("drive: model=%r firmware=%r sectors=%d" % (model, fw, sectors))
    print("features: download-microcode=%s segmented=%s min/max blocks=%d/%d" % (bool(w[83] & 1), bool(w[119] & 0x10), w[234], w[235]))
    if model != EXPECT_MODEL:
        die("model is not %s" % EXPECT_MODEL)
    if fw != EXPECT_FW:
        die("firmware is %s, expected %s (already updated?)" % (fw, EXPECT_FW))
    if sectors != EXPECT_SECTORS:
        die("capacity mismatch")
    if not (w[83] & 1 and w[119] & 0x10 and w[234] <= CHUNK <= w[235]):
        die("drive does not advertise segmented microcode download for %d-block chunks" % CHUNK)
    bad = smart_bad(fd)
    if bad is None:
        die("could not read SMART data")
    if bad:
        die("SMART attributes at or below threshold: %s" % bad)
    print("SMART: no attribute at or below its threshold")
    total = len(data) // 512
    full, rest = divmod(total, CHUNK)
    print("plan: %d x DOWNLOAD MICROCODE (0x92) mode 3, %d blocks each, plus 1 x %d blocks, then STANDBY IMMEDIATE" % (full, CHUNK, rest))
    if not do_flash:
        print("DRY RUN - nothing was written to the drive")
        return 0
    if not confirmed:
        die("refusing to flash without --confirm=FLASH-MY-SC311")
    if os.geteuid() != 0:
        die("must run as root")
    if "--no-wait" not in args:
        print("flashing in 10 seconds - Ctrl-C to abort. Keep AC power connected.")
        time.sleep(10)
    off = 0
    while off < total:
        n = min(CHUNK, total - off)
        buf = ctypes.create_string_buffer(data[off * 512:(off + n) * 512], n * 512)
        cdb = [0x85, 0x0A, 0x06, 0, 0x03, 0, n & 0xFF, 0, (n >> 8) & 0xFF, 0, off & 0xFF, 0, (off >> 8) & 0xFF, 0xE0, 0x92, 0]
        ok, h = sg(fd, cdb, TO_DEV, buf)
        if not ok:
            die("DOWNLOAD MICROCODE failed at block %d (status=%d host=%d driver=%d) - stopped; do not power off, re-run to retry" % (off, h.status, h.host_status, h.driver_status))
        off += n
        sys.stdout.write(".")
        sys.stdout.flush()
    print()
    ok, h = sg(fd, [0x85, 0x06, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xE0, 0xE0, 0], NONE)
    print("download complete (%d blocks); STANDBY IMMEDIATE %s" % (total, "ok" if ok else "failed"))
    w = identify(fd)
    print("firmware now reports: %s (a full power cycle may be needed before it changes)" % text(w[23:27]))
    return 0


sys.exit(main())
