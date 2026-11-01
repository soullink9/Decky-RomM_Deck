"""Motion: calibration from simulated poses, the DSU output axes, and the server over real UDP."""
import math, os, socket, struct, sys, tempfile, threading, time, zlib, types
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["DECKY_USER_HOME"] = str(tmp)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from romm_deck import config, motion as MO
config.SETTINGS_DIR = tmp / "settings"; config.SETTINGS_DIR.mkdir()

fails = 0
def check(ok, msg):
    global fails
    print(("PASS " if ok else "FAIL ") + msg); fails += 0 if ok else 1

G = 9.80665
def rot(axis, deg):  # rotation matrix about a unit axis (world frame)
    x, y, z = axis; c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg)); t = 1 - c
    return [[t*x*x + c, t*x*y - s*z, t*x*z + s*y], [t*x*y + s*z, t*y*y + c, t*y*z - s*x], [t*x*z - s*y, t*y*z + s*x, t*z*z + c]]
def mul(A, v): return [sum(A[i][j] * v[j] for j in range(3)) for i in range(3)]
def matmul(A, B): return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def T(A): return [list(r) for r in zip(*A)]

# World: x right, y up, z toward the player. Device axes R, U, F (right, top edge, out of the screen).
# Pose = device-to-world rotation. Upright facing you = identity. Flat, screen up = 90° about x (back).
UPRIGHT = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
FLAT = rot([1, 0, 0], -90)  # top edge goes away, screen faces up

class FakeSensor:
    """A sensor mounted in the device with `mount` (device -> sensor axes); `mirror` negates sensor x."""
    name = "fake-imu"
    def __init__(self, mount, mirror=False):
        self.mount, self.mirror, self.pose, self.w_world = mount, mirror, FLAT, [0, 0, 0]
    def _to_sensor(self, v_world):
        v_dev = mul(T(self.pose), v_world)
        s = mul(self.mount, v_dev)
        return [-s[0], s[1], s[2]] if self.mirror else s
    def read(self):
        return self._to_sensor([0, G, 0]), self._to_sensor(self.w_world)
    def close(self): pass

def scripted(sensor, steps):
    """Fake clock: plays the poses (time -> pose, angular velocity) as calibrate() samples."""
    now = [0.0]
    def clock(): return now[0]
    def sleep(dt):
        now[0] += dt
        for t0, t1, fn in steps:
            if t0 <= now[0] < t1:
                fn(sensor, (now[0] - t0) / (t1 - t0), t1 - t0)
    return clock, sleep

def lift(sensor, frac, dur):  # flat -> upright: +90° about the device's right axis (world x)
    sensor.pose = rot([1, 0, 0], -90 + 90 * frac)
    sensor.w_world = [math.radians(90) / dur, 0, 0]
def hold(pose):
    def f(sensor, frac, dur): sensor.pose, sensor.w_world = pose, [0, 0, 0]
    return f

def calibrate(sensor, steps):
    clock, sleep = scripted(sensor, steps)
    msgs = []
    MO.calibrate(msgs.append, sensor=sensor, sleep=sleep, clock=clock, timeout=30)
    return msgs

def expected(pose, w_world=(0, 0, 0)):
    """What SteamDeckGyroDSU would send for a Deck in this pose: accel x=-R y=-F z=+U, pitch=R yaw=-F roll=U."""
    a = mul(T(pose), [0, 1, 0]); w = mul(T(pose), list(w_world))
    return (-a[0], -a[2], a[1], math.degrees(w[0]), -math.degrees(w[2]), math.degrees(w[1]))

def close(a, b, tol=0.02): return all(abs(x - y) < tol * max(1, abs(y)) for x, y in zip(a, b))

STEPS = [(0, 4, hold(FLAT)), (4, 5, lift), (5, 9, hold(UPRIGHT))]
mounts = {
    "sensor axes = device axes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "Ally X-like (x, z, -y)": [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
    "odd tilted mount": matmul(rot([0.6, 0.0, 0.8], 50), rot([0, 1, 0], 120)),
}
for label, mount in mounts.items():
    for mirror in (False, True):
        s = FakeSensor(mount, mirror)
        msgs = calibrate(s, STEPS)
        rows = config.load(MO.CALIBRATION)["rows"]
        ok = msgs[-1] == "Calibrated"
        for pose_name, pose, w in [
            ("flat", FLAT, (0, 0, 0)), ("upright", UPRIGHT, (0, 0, 0)),
            ("tilted right side down", rot([0, 0, 1], -30), (0, 0, 0)),
            ("tilted forward", rot([1, 0, 0], -40), (0, 0, 0)),
            ("turning (yaw) while upright", UPRIGHT, (0, 1.0, 0)),
            ("tilting top back (pitch)", UPRIGHT, (1.0, 0, 0)),
            ("steering (roll)", UPRIGHT, (0, 0, 1.0)),
        ]:
            s.pose, s.w_world = pose, list(w)
            a, g = s.read()
            got = MO.to_dsu(rows, a, g)
            if not close(got, expected(pose, w)):
                ok = False
                print(f"   {label} mirror={mirror} {pose_name}: got {[round(x, 3) for x in got]} want {[round(x, 3) for x in expected(pose, w)]}")
        check(ok, f"calibrated then sent like a Steam Deck: {label}{', mirrored axes' if mirror else ''}")

# known values: flat on a table reads 1 g "down" on y; upright 1 g on z (as SteamDeckGyroDSU sends a Deck)
check(close(expected(FLAT)[:3], (0, -1, 0)) and close(expected(UPRIGHT)[:3], (0, 0, 1)), "reference: flat (0,-1,0) g, upright (0,0,1) g")

# mistakes are explained, nothing saved
config.save(MO.CALIBRATION, {})
s = FakeSensor(mounts["Ally X-like (x, z, -y)"])
try:
    calibrate(s, [(0, 100, hold(FLAT))]); check(False, "never stood up: error")
except MO.SensorError as e:
    check("stood up" in str(e) and not MO.calibrated(), f"never stood up: {e}")
try:
    tilt_only = lambda sensor, frac, dur: (setattr(sensor, "pose", rot([1, 0, 0], -90 + 40 * frac)), setattr(sensor, "w_world", [math.radians(40) / dur, 0, 0]))
    calibrate(s, [(0, 4, hold(FLAT)), (4, 5, tilt_only), (5, 9, hold(rot([1, 0, 0], -50)))]); check(False, "only tilted 40°: error")
except MO.SensorError as e:
    check("quarter turn" in str(e) and not MO.calibrated(), f"only tilted a little: {e}")

# ---- the real sysfs-style sensor reader ----
iio = tmp / "iio/iio:device0"; iio.mkdir(parents=True)
(iio / "name").write_text("bmi323-imu\n")
for k, vals, scale in (("accel", (10, -20, 16384), 0.000598), ("anglvel", (1, 2, 3), 0.001065)):
    for axis, v in zip("xyz", vals): (iio / f"in_{k}_{axis}_raw").write_text(f"{v}\n")
    (iio / f"in_{k}_scale").write_text(f"{scale}\n")
MO.IIO = tmp / "iio"
sen = MO.Sensor()
a, g = sen.read()
check(sen.name == "bmi323-imu" and abs(a[2] - 16384 * 0.000598) < 1e-9 and abs(g[1] - 2 * 0.001065) < 1e-9, f"reads the kernel's sensor files with their scale: {a} {g}")
(iio / "in_accel_z_raw").write_text("100\n"); a, _ = sen.read()
check(abs(a[2] - 100 * 0.000598) < 1e-9, "every read is fresh")
sen.close()
MO.IIO = tmp / "nothing"
try:
    MO.Sensor(); check(False, "no sensor")
except MO.SensorError as e:
    check("No motion sensor" in str(e), f"no sensor: {e}")

# ---- InputPlumber's virtual Steam Deck controller (when the sensor itself is busy) ----
hid = tmp / "hidraw"; dev = tmp / "dev"; dev.mkdir()
for n, hid_id in (("hidraw1", "0003:00000B05:00001B4C"), ("hidraw4", "0003:000028DE:000012FD")):
    (hid / n / "device").mkdir(parents=True); (hid / n / "device/uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME=x\n")
os.mkfifo(dev / "hidraw4")
MO.HIDRAW, MO.DEV = hid, dev
path, product = MO.find_deck_report()
check(path == dev / "hidraw4" and product == 0x12FD, f"finds InputPlumber's Steam Deck-style controller, not the Ally's own pad: {path}")
def report(acc, gyr, frame=0):
    r = bytearray(64); r[0], r[2], r[3] = 1, 9, 64
    struct.pack_into("<I", r, 4, frame); struct.pack_into("<6h", r, 24, *acc, *gyr)
    return bytes(r)
writer = os.open(dev / "hidraw4", os.O_RDWR)  # (keeps the pipe open like a device)
d = MO.DeckReportSensor()
os.write(writer, report((0, 0, 100), (0, 0, 0), 1) + report((0, 16384, 0), (164, 0, -164), 2))
a, g = d.read()
check(d.name == "steam-deck-controller:12fd" and abs(a[1] - G) < 1e-6 and abs(math.degrees(g[0]) - 10.009) < 0.01
      and abs(math.degrees(g[2]) + 10.009) < 0.01, f"reads the newest report, scaled (1 g, 10 °/s): {a} {[math.degrees(x) for x in g]}")
a2, _ = d.read()
check(a2 == a, "no new report: keeps the last one")
# the sensor busy (InputPlumber 0.82+ streams from it): falls back to the controller
MO.IIO = tmp / "iio"
real_read = MO.Sensor.read
def busy(self): raise MO.SensorError("Can't read the motion sensor ([Errno 16] Device or resource busy)")
MO.Sensor.read = busy
os.write(writer, report((0, 0, 16384), (0, 0, 0), 3))
s2 = MO.open_sensor()
check(isinstance(s2, MO.DeckReportSensor), f"sensor busy: uses InputPlumber's controller instead ({s2.name})")
s2.close()
MO.Sensor.read = real_read
s3 = MO.open_sensor()
check(isinstance(s3, MO.Sensor), "sensor readable: reads it directly (first choice)"); s3.close()
# calibrated with one source, now the other: asked to recalibrate rather than sending wrong axes
config.save(MO.CALIBRATION, {"sensor": "bmi323-imu", "rows": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]})
try:
    MO.serve(lambda: False, MO.DeckReportSensor()); check(False, "source changed")
except MO.SensorError as e:
    check("Recalibrate" in str(e), f"motion source changed since calibrating: {e}")
# neither works: both reasons given
MO.Sensor.read = busy; os.close(writer); (dev / "hidraw4").unlink()
try:
    MO.open_sensor(); check(False, "nothing readable")
except MO.SensorError as e:
    check("busy" in str(e) and "InputPlumber" in str(e), f"nothing readable: {e}")
MO.Sensor.read = real_read
d.close()

# ---- the server, over UDP, as Ryujinx talks to it ----
rows = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
s = FakeSensor(rows); s.pose = FLAT
running = [True]; ready = threading.Event()
t = threading.Thread(target=MO.serve, args=(lambda: running[0], s, rows, ready.set), daemon=True); t.start()
ready.wait(3)
c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); c.settimeout(2)
def req(kind, payload=b""):
    body = struct.pack("<I", kind) + payload
    pkt = b"DSUC" + struct.pack("<HHII", 1001, len(body), 0, 1234) + body
    pkt = pkt[:8] + struct.pack("<I", zlib.crc32(pkt) & 0xFFFFFFFF) + pkt[12:]
    c.sendto(pkt, (MO.HOST, MO.PORT))
def recv():
    d, _ = c.recvfrom(2048)
    crc = struct.unpack_from("<I", d, 8)[0]
    ok = zlib.crc32(d[:8] + b"\0\0\0\0" + d[12:]) & 0xFFFFFFFF == crc and d[:4] == b"DSUS" and struct.unpack_from("<H", d, 6)[0] == len(d) - 16
    return ok, struct.unpack_from("<I", d, 16)[0], d[20:]
req(0x100000); ok, kind, p = recv()
check(ok and kind == 0x100000 and struct.unpack("<H", p)[0] == 1001, "answers the protocol version (valid header and checksum)")
req(0x100001, struct.pack("<i", 2) + bytes([0, 1]))
r0, r1 = recv(), recv()
check(r0[0] and r0[2][:4] == bytes([0, 2, 2, 1]) and r1[2][:2] == bytes([1, 0]), "slot 0 is a connected full-gyro controller, slot 1 empty")
req(0x100002, bytes([1, 0]) + bytes(6))
ok, kind, p = recv()
check(ok and kind == 0x100002 and len(p) == 80, f"motion packets are the standard 100 bytes ({len(p) + 20})")
vals = struct.unpack_from("<Q6f", p, 48)
check(close(vals[1:4], (0, -1, 0)), f"lying flat: accel {[round(v, 3) for v in vals[1:4]]} g")
s.pose = UPRIGHT; time.sleep(0.1)
for _ in range(30): ok, kind, p = recv()
vals2 = struct.unpack_from("<Q6f", p, 48)
check(close(vals2[1:4], (0, 0, 1)) and vals2[0] > vals[0], f"stood up: accel {[round(v, 3) for v in vals2[1:4]]} g, timestamps move on")
n1 = struct.unpack_from("<I", p, 12)[0]; ok, kind, p = recv(); n2 = struct.unpack_from("<I", p, 12)[0]
check(n2 == n1 + 1, "packet numbers count up")
# a second server can't take the port: clear reason
try:
    MO.serve(lambda: False, FakeSensor(rows), rows); check(False, "port busy")
except MO.SensorError as e:
    check("already using port" in str(e), f"port in use: {e}")
running[0] = False; t.join(3)
check(not t.is_alive(), "stops when told to")

print(f"\n{fails} failures"); sys.exit(1 if fails else 0)
