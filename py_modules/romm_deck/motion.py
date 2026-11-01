"""The handheld's motion sensor, served to Ryujinx as a CemuHook (DSU) motion source.

Why: on the ROG Ally family under InputPlumber, the usual route (EmuDeck's Steam Deck motion
server) doesn't work: it only looks for a real Steam Deck, and InputPlumber's virtual one up to
0.81 also sent the accelerometer ~1600x too small (ShadowBlip/InputPlumber#715). Without the
accelerometer a game can't tell which way is down, so tilting does nothing.

So the plugin reads the motion itself, from whichever of these works:
  1. the sensor, straight from the kernel (/sys/bus/iio/devices). Works while nothing streams
     from it, i.e. InputPlumber 0.81 and older.
  2. InputPlumber's virtual Steam Deck controller (a hidraw device, Valve vendor id). From 0.82
     InputPlumber streams from the sensor (the kernel then says "busy" to anyone else), and fixed
     that controller's scaling, so its motion is usable.
and serves it on 127.0.0.1:26760, the address the preset points Ryujinx's motion at.

Either way the axes depend on the model (InputPlumber's own orientation for the Xbox Ally is marked
"verify on actual hardware"), so it's calibrated once (calibrate()): lay the device flat, then stand
it up facing you. That gives the screen's and the top edge's directions; the gyro during the lift
double-checks left/right.

Axes sent (as SteamDeckGyroDSU does on a Steam Deck, which games are known to read correctly),
for a device with right side R, top edge U and screen-front F:
  accel (g):    x = -R, y = -F, z = +U       gyro (deg/s): pitch = +R, yaw = -F, roll = +U
"""
import math
import os
import random
import socket
import struct
import time
import zlib
from pathlib import Path

from . import config

IIO = Path(os.environ.get("ROMM_DECK_IIO", "/sys/bus/iio/devices"))  # (the tests use fakes for these)
HIDRAW = Path(os.environ.get("ROMM_DECK_HIDRAW", "/sys/class/hidraw"))
DEV = Path(os.environ.get("ROMM_DECK_DEV", "/dev"))
VALVE = 0x28DE  # Steam Deck: 0x1205; InputPlumber's virtual ones: 0x12f0-0x12ff (0x12fd = ROG Ally)
DECK_ACCEL = 9.80665 / 16384     # m/s² per unit in a Steam Deck input report (16384 = 1 g)
DECK_GYRO = (2000 / 32768) * (3.141592653589793 / 180)  # rad/s per unit (±2000 °/s)
HOST, PORT = "127.0.0.1", 26760  # the standard DSU address, which EmuDeck's emulator configs already use
CALIBRATION = "motion-calibration"  # settings/motion-calibration.json
G = 9.80665  # standard gravity, m/s²
RATE = 125  # samples per second while a game is asking (emulators poll at 60-120 Hz)


class SensorError(Exception):
    """The motion can't be read; the message says why, in words for the game page."""


# ---------- the sensor ----------

def open_sensor():
    """The first motion source that can be read right now (see the top of the file)."""
    reasons = []
    for kind in (Sensor, DeckReportSensor):
        try:
            sensor = kind()
        except SensorError as e:
            reasons.append(str(e))
            continue
        try:
            sensor.read()
            return sensor
        except SensorError as e:
            sensor.close()
            reasons.append(str(e))
    raise SensorError("; ".join(reasons))


def find_sensor():
    """The first IIO device with a 3-axis accelerometer and gyroscope, or None."""
    for dev in sorted(IIO.glob("iio:device*")):
        if all((dev / f"in_{kind}_{axis}_raw").exists() for kind in ("accel", "anglvel") for axis in "xyz"):
            return dev
    return None


class Sensor:
    """Reads accelerometer (m/s²) and gyroscope (rad/s) in the sensor's own axes."""

    def __init__(self, dev=None):
        """Open the sensor at `dev` (an /sys/bus/iio/devices/iio:deviceN folder), or the first one found."""
        dev = dev or find_sensor()
        if not dev:
            raise SensorError("No motion sensor found on this device")
        self.dev = Path(dev)
        self.name = _read(self.dev / "name") or self.dev.name
        self.fds, self.scale, self.offset = {}, {}, {}
        try:
            for kind in ("accel", "anglvel"):
                for axis in "xyz":
                    key = f"{kind}_{axis}"
                    # Kept open and re-read with pread: reopening six files 125 times a second is slow
                    self.fds[key] = os.open(self.dev / f"in_{key}_raw", os.O_RDONLY)
                    self.scale[key] = float(self._attribute(kind, axis, "scale") or 1)
                    self.offset[key] = float(self._attribute(kind, axis, "offset") or 0)
        except (OSError, ValueError) as e:
            self.close()
            raise SensorError(f"Can't read the motion sensor ({e})") from None

    def _attribute(self, kind, axis, name):
        """An IIO attribute such as the scale: per axis (in_accel_x_scale) if the driver has one,
        else shared by all axes (in_accel_scale). "" if neither exists."""
        return _read(self.dev / f"in_{kind}_{axis}_{name}") or _read(self.dev / f"in_{kind}_{name}")

    def read(self):
        """((ax, ay, az) m/s², (gx, gy, gz) rad/s): IIO's raw counts, plus offset, times scale."""
        values = {}
        try:
            for key, fd in self.fds.items():
                raw = int(os.pread(fd, 32, 0))
                values[key] = (raw + self.offset[key]) * self.scale[key]
        except (OSError, ValueError) as e:  # e.g. busy: something else switched the sensor to streaming
            raise SensorError(f"Can't read the motion sensor ({e})") from None
        accel = (values["accel_x"], values["accel_y"], values["accel_z"])
        gyro = (values["anglvel_x"], values["anglvel_y"], values["anglvel_z"])
        return accel, gyro

    def close(self):
        """Close the sensor's files."""
        for fd in self.fds.values():
            os.close(fd)
        self.fds = {}


def find_deck_report():
    """(/dev/hidrawN, product id) of a Steam Deck-style controller (real, or InputPlumber's virtual
    one), or (None, None)."""
    for node in sorted(HIDRAW.glob("hidraw*")):
        for line in _read(node / "device/uevent").splitlines():
            if line.startswith("HID_ID="):  # e.g. HID_ID=0003:000028DE:000012FD (bus:vendor:product)
                _, vendor, product = (int(part, 16) for part in line[7:].split(":"))
                is_deck = product == 0x1205
                is_inputplumber = 0x12F0 <= product <= 0x12FF
                if vendor == VALVE and (is_deck or is_inputplumber):
                    return DEV / node.name, product
    return None, None


class DeckReportSensor:
    """Motion from a Steam Deck-style controller's input reports (64 bytes: accel at bytes 24-29,
    gyro at 30-35, little-endian int16), in the report's own axes."""

    def __init__(self, path=None, product=0x12FD):
        """Open the controller's /dev/hidrawN (`path`), or find one. `product` names the calibration,
        since the hidraw number can change between boots but the product id doesn't."""
        if not path:
            path, product = find_deck_report()
        if not path:
            raise SensorError("No Steam Deck-style controller from InputPlumber found")
        self.name = f"steam-deck-controller:{product:04x}"  # (hidrawN can change between boots)
        try:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            raise SensorError(f"Can't read InputPlumber's controller ({e})") from None
        self.last = None

    def read(self):
        """((ax, ay, az) m/s², (gx, gy, gz) rad/s), from the newest report."""
        deadline = time.monotonic() + 0.5
        while True:
            try:
                while True:  # drain: keep only the newest report
                    report = os.read(self.fd, 64)
                    if not report:  # (only a test pipe ends like this; a device just waits)
                        break
                    # report id 1, type 9: the Deck's full input state (other reports carry no motion)
                    if len(report) >= 36 and report[0] == 0x01 and report[2] == 0x09:
                        self.last = report
            except BlockingIOError:
                pass
            except OSError as e:
                raise SensorError(f"Can't read InputPlumber's controller ({e})") from None
            if self.last is not None:
                break
            if time.monotonic() > deadline:
                raise SensorError("InputPlumber's controller isn't sending motion")
            time.sleep(0.005)
        ax, ay, az, gx, gy, gz = struct.unpack_from("<6h", self.last, 24)
        return (ax * DECK_ACCEL, ay * DECK_ACCEL, az * DECK_ACCEL), (gx * DECK_GYRO, gy * DECK_GYRO, gz * DECK_GYRO)

    def close(self):
        """Close the controller's device file."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


# ---------- calibration ----------

def calibrated():
    """Has the motion been calibrated on this device (see calibrate)?"""
    return bool(config.load(CALIBRATION).get("rows"))


def calibrate(progress, sensor=None, sleep=time.sleep, clock=time.monotonic, timeout=45):
    """Two poses: flat (screen up), then stood up facing you. progress(text) tells the user what
    to do. Saves the result; raises SensorError with a plain reason if it didn't work."""
    own = sensor is None
    sensor = sensor or open_sensor()
    try:
        progress("Lay it flat on a table, screen up, and let go")
        sleep(1.5)  # time to put it down
        flat, _ = _wait_still(sensor, sleep, clock, timeout)
        progress("Got it. Now stand it up on its bottom edge, screen facing you, and hold still")
        upright, turned = _wait_still(sensor, sleep, clock, timeout, after_moving=True)
    finally:
        if own:
            sensor.close()

    F = _unit(flat)
    if abs(math.degrees(math.acos(max(-1, min(1, _dot(F, _unit(upright)))))) - 90) > 35:
        raise SensorError("Stand it up straight (screen facing you), about a quarter turn from flat. Try again")
    U = _unit(_sub(upright, _scale(F, _dot(upright, F))))
    R = _cross(U, F)
    lift = math.degrees(_dot(turned, R))  # flat to upright is a +90° turn around the right-hand axis
    if abs(lift) < 40:
        raise SensorError("Didn't see it being stood up. Try again, a bit slower")
    if lift < 0:  # the sensor's axes are mirrored: right is the other way
        R = _scale(R, -1)
    config.save(CALIBRATION, {"sensor": sensor.name, "rows": [R, U, F], "at": time.strftime("%Y-%m-%d %H:%M")})
    progress("Calibrated")
    config.log.info("Motion calibrated: R=%s U=%s F=%s (lift %.0f°)", R, U, F, lift)


def _wait_still(sensor, sleep, clock, timeout, after_moving=False):
    """Average accel over 1 s of holding still. With after_moving: only once it has turned at
    least 30° first. Also returns the turn (rad, per sensor axis) up to that point."""
    start = last = clock()
    turned = [0.0, 0.0, 0.0]
    window = []
    moved = not after_moving
    while clock() - start < timeout:
        a, w = sensor.read()
        now = clock()
        dt, last = now - last, now
        turned = [t + wi * dt for t, wi in zip(turned, w)]
        if not moved and math.degrees(_norm(turned)) > 30:
            moved, window = True, []
        still = _norm(w) < math.radians(4) and abs(_norm(a) - G) < 0.15 * G
        window = window + [(now, a)] if still and moved else []
        if window and now - window[0][0] >= 1.0:
            n = len(window)
            return [sum(s[1][i] for s in window) / n for i in range(3)], turned
        sleep(1 / 100)
    if not moved:
        raise SensorError("Didn't see it being stood up. Try again")
    raise SensorError("It didn't settle. Hold it still and try again")


# ---------- the DSU (CemuHook) server ----------

def to_dsu(rows, accel, gyro):
    """Sensor readings -> (accX, accY, accZ in g, pitch, yaw, roll in deg/s), see the top of the file."""
    R, U, F = rows
    aR, aU, aF = (_dot(r, accel) / G for r in (R, U, F))
    gR, gU, gF = (math.degrees(_dot(r, gyro)) for r in (R, U, F))
    return -aR, -aF, aU, gR, -gF, gU


def serve(keep_going, sensor=None, rows=None, ready=None, rate=RATE):
    """Serve motion on 127.0.0.1:26760 until keep_going() is False (checked every second)."""
    sensor = sensor or open_sensor()  # fails now, not mid-game
    if rows is None:
        cal = config.load(CALIBRATION)
        if cal.get("sensor") != sensor.name:
            sensor.close()
            raise SensorError(f"Motion now comes from {sensor.name} (calibrated with {cal.get('sensor')}): "
                              "press Recalibrate motion")
        rows = cal["rows"]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, PORT))
    except OSError:
        raise SensorError(f"Another motion server is already using port {PORT}") from None
    sock.setblocking(False)
    if ready:
        ready()
    server_id, number, clients, checked = random.getrandbits(32), 0, {}, time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if now - checked >= 1:
                checked = now
                if not keep_going():
                    return
                clients = {a: t for a, t in clients.items() if now - t < 5}  # clients repeat requests
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                except (BlockingIOError, InterruptedError):
                    break
                for reply in _answer(data, server_id):
                    if reply is None:
                        clients[addr] = now
                    else:
                        sock.sendto(reply, addr)
            if clients:
                accel, gyro = sensor.read()
                number = (number + 1) & 0xFFFFFFFF
                pkt = _packet(0x100002, server_id, _data(number, to_dsu(rows, accel, gyro)))
                for addr in clients:
                    try:
                        sock.sendto(pkt, addr)
                    except OSError:
                        pass
            time.sleep(1 / rate)
    finally:
        sock.close()
        sensor.close()


def _answer(data, server_id):
    """Replies to one client request; None in the list means 'send this client motion data'."""
    if len(data) < 20 or data[:4] != b"DSUC":
        return []
    kind = struct.unpack_from("<I", data, 16)[0]
    if kind == 0x100000:  # protocol version
        return [_packet(0x100000, server_id, struct.pack("<H", 1001))]
    if kind == 0x100001:  # which controllers are connected
        count = struct.unpack_from("<i", data, 20)[0] if len(data) >= 24 else 0
        slots = data[24:24 + max(0, min(count, 4))]
        return [_packet(0x100001, server_id, _slot(s) + b"\0") for s in slots]
    if kind == 0x100002:  # subscribe to motion data
        return [None]
    return []


def _slot(slot):
    """slot, state (2 connected), model (2 full gyro), connection (1 USB), MAC, battery (5 full)."""
    return struct.pack("<BBBB6sB", slot, 2, 2, 1, b"\0" * 6, 5) if slot == 0 else \
        struct.pack("<BBBB6sB", slot, 0, 0, 0, b"\0" * 6, 0)


def _data(number, motion):
    """A DSU "controller data" message for slot 0: a connected controller with no buttons pressed
    and centred sticks (only the motion matters), a timestamp in microseconds, then accel and gyro."""
    return (_slot(0) + struct.pack("<BI", 1, number)
            + bytes(4)                 # buttons, home, touch button
            + bytes([128] * 4)         # sticks centered
            + bytes(12) + bytes(12)    # analog buttons, two touches
            + struct.pack("<Q6f", time.monotonic_ns() // 1000, *motion))


def _packet(kind, server_id, payload):
    """A complete DSU message: "DSUS", protocol 1001, length, CRC32 (computed with the CRC field
    zeroed, as the protocol says), our server id, the message type, then the payload."""
    body = struct.pack("<I", kind) + payload
    pkt = b"DSUS" + struct.pack("<HHII", 1001, len(body), 0, server_id) + body
    return pkt[:8] + struct.pack("<I", zlib.crc32(pkt) & 0xFFFFFFFF) + pkt[12:]


# ---------- helpers ----------

def _read(path):
    """A small sysfs file's contents, or "" if it can't be read."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


# Small 3-D vector helpers for calibration (no numpy: Decky's Python can't install packages)

def _dot(a, b):
    """a · b"""
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    """|a|"""
    return math.sqrt(_dot(a, a))


def _unit(a):
    """a scaled to length 1"""
    n = _norm(a) or 1
    return [x / n for x in a]


def _sub(a, b):
    """a - b"""
    return [x - y for x, y in zip(a, b)]


def _scale(a, k):
    """a × k (a number)"""
    return [x * k for x in a]


def _cross(a, b):
    """a × b (cross product)"""
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
