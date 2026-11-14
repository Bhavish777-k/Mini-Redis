#!/usr/bin/env python3
"""Small workload to demonstrate Phase 9 live metrics in the local dashboard."""
import socket
import time


def command(text):
    with socket.create_connection(('127.0.0.1', 7001), timeout=3) as s:
        s.settimeout(3)
        s.sendall((text + '\n').encode())
        data = bytearray()
        while b'\n' not in data:
            part = s.recv(4096)
            if not part:
                raise ConnectionError('Router closed connection')
            data.extend(part)
        return data.split(b'\n', 1)[0].decode()


if __name__ == '__main__':
    assert command('SET phase9:demo active') == 'OK'
    print('Sending GET requests for about 6 seconds. Watch Monitoring in the dashboard.')
    deadline = time.monotonic() + 6
    count = 0
    while time.monotonic() < deadline:
        assert command('GET phase9:demo') == 'active'
        count += 1
        time.sleep(0.02)
    print('Requests sent:', count)
    print('Router metrics:', command('METRICS'))
