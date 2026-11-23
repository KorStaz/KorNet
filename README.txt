KORNET — NETWORK MONITOR AND PRIVATE LAN SCANNER
=================================================

BRANDING
- Uses the supplied KorNet Network-K artwork as the Windows executable icon
  and Tkinter window icon. Original PNG artwork is included in assets/.

FEATURES
- Dashboard with measurable local connection counters and local IPv4 address.
- Live Windows socket monitor using psutil.net_connections(kind="inet").
- TCP/UDP endpoint visibility, process/PID information where permissions allow.
- Search, localhost/private-IP filters, and CSV export for displayed connections.
- Session peer observation with first/last seen timestamps and disconnected history.
- Private IPv4 TCP scanner: custom port, common ports, and ports 1–65535.
- Bounded scan concurrency, progress reporting, cancellation, and CSV export.
- Persistent settings stored under %APPDATA%\KorNet\settings.json.
- Dark Tkinter interface with Dashboard, Connection Monitor, Peer Detection,
  LAN Scanner, and Settings tabs.

IMPORTANT LIMITATIONS
- Socket visibility depends on Windows permissions. Some records or process
  names may be unavailable unless KorNet is run with elevated permissions.
- A remote endpoint is not proof of a physical device or a person's identity.
  VPNs, NAT, proxies, relays, and game services can affect the visible endpoint.
- UDP is connectionless; UDP endpoints are not labelled established.
- Direction is conservative. KorNet reports Unknown when it cannot determine it.
- Peer history is session-only and begins when KorNet starts monitoring.
- The scanner tests TCP connect availability only. It does not scan UDP, perform
  service fingerprinting, or guarantee detection of every online device.
- Only scan private networks you own or are authorised to test.
- Full port scans can take a long time. Stop is cooperative and outstanding
  socket operations finish when their timeout expires.
- This application does not bypass firewalls or change network services.

RUN FROM SOURCE
1. Install Python 3.10 or newer on Windows.
2. Open a terminal in the extracted KorNet_Upgraded folder.
3. Run: py -3 -m pip install -r requirements.txt
4. Run: py -3 source\lan_scanner.py

BUILD WINDOWS EXECUTABLE
1. Open the KorNet_Upgraded folder on Windows.
2. Double-click build_windows.bat.
3. The standalone executable is created at dist\KorNet.exe.
4. Keep the source folder and build files if you want to rebuild later.

The supplied ZIP contains source and build configuration. It does not include a
prebuilt executable unless one is explicitly present in the ZIP.
