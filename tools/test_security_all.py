"""Run every security probe in one go.

    python tools/test_security_all.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = [
    "test_security.py",
    "test_security_probe.py",
    "test_security_probe2.py",
    "test_security_probe5.py",
    "test_security_probe6.py",
    "test_security_probe7.py",
    "test_security_probe8.py",
    "test_security_probe9.py",
    "test_security_probe10.py",
    "test_security_probe11.py",
    "test_security_probe12.py",
    "test_security_probe13.py",
    "test_admin_sync.py",
    "test_admin_login_sync.py",
    "test_admin_sync_offline.py",
]
# The stub panels listen on these ports. A probe that died without
# cleaning up leaves its port taken, and the next run cannot bind it.
STUB_PORTS = range(8131, 8153)


def free_stub_ports() -> None:
    """Make sure no stub panel is still holding a port."""
    for port in STUB_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                print(f"  (port {port} is still in use, waiting)")
                for _ in range(20):
                    try:
                        sock.bind(("127.0.0.1", port))
                        break
                    except OSError:
                        import time

                        time.sleep(0.5)


failed = []
for name in SCRIPTS:
    print("=" * 70)
    print(name)
    print("=" * 70)
    free_stub_ports()
    r = subprocess.run([sys.executable, os.path.join(HERE, name)],
                       cwd=os.path.dirname(HERE))
    if r.returncode:
        failed.append(name)

print()
print("=" * 70)
if failed:
    print("FAILED suites:", ", ".join(failed))
    sys.exit(1)
print("ALL SUITES RAN")
