"""Plays Ryujinx's part: asks 127.0.0.1:26760 (or ROMM_DECK_DSU_PORT, as the tests set it) for motion and
prints one reading (accel xyz, gyro pyr)."""
import os, socket, struct, zlib
PORT = int(os.environ.get("ROMM_DECK_DSU_PORT") or 26760)
def pkt(kind, payload=b""):
    body = struct.pack("<I", kind) + payload
    p = b"DSUC" + struct.pack("<HHII", 1001, len(body), 0, 7) + body
    return p[:8] + struct.pack("<I", zlib.crc32(p) & 0xFFFFFFFF) + p[12:]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(2)
try:
    s.sendto(pkt(0x100002, bytes([1, 0]) + bytes(6)), ("127.0.0.1", PORT))
    d, _ = s.recvfrom(2048)
    print(*[f"{v:.3f}" for v in struct.unpack_from("<6f", d, 20 + 56)])
except OSError as e:
    print("no-motion", e)
