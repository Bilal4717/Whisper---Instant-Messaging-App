# Whisper — Instant Messaging App

A real-time, multi-client chat system built for the **Computer Networks** course.
Server and clients communicate over plain TCP sockets using a custom JSON
protocol with 4-byte length-prefix framing. The client ships a WhatsApp-inspired
Tkinter GUI.

---

## ✨ Features

- **Multi-client server** — handles many concurrent users via per-connection threads
- **Private (1-to-1) messaging** between any two logged-in users
- **Group chat** broadcast to every online user
- **Live user list** with join / leave notifications
- **Non-blocking GUI** — background receiver thread + Tk `after()` poller
- **WhatsApp-style UI** — green chat bubbles, day separators, ✓✓ ticks, emoji picker,
  avatar circles, unread badges
- **Configurable host & port** via command-line flags
- Pure Python 3 — **no third-party dependencies**

---

## 📁 Project Structure

```
.
├── server.py     # Multi-threaded TCP server (router + user registry)
├── client_final.py  # Tkinter GUI client (WhatsApp-inspired)
├── REPORT_TEMPLATE.md
└── README.md
```

---

## 🛠 Requirements

- Python **3.8+** (Tkinter ships with the standard CPython installer)
- Any OS with a TCP/IP stack (Windows, macOS, Linux)

No `pip install` needed.

---

## 🚀 Quick Start (single machine)

Open **three** terminals.

**Terminal 1 — start the server**
```bash
python server.py
# → Server listening on 0.0.0.0:5555
```

**Terminal 2 — first client**
```bash
python client_final.py
# log in as: alice
```

**Terminal 3 — second client**
```bash
python client_final.py
# log in as: bob
```

Now click `bob` in alice's sidebar (or vice-versa) and start chatting. Click
**Group** to broadcast to everyone.

---

## 🌐 LAN Deployment

1. Find the server machine's LAN IP (`ipconfig` on Windows, `ifconfig` / `ip a` on
   Linux/macOS), e.g. `192.168.1.10`.
2. On the server machine:
   ```bash
   python server.py --host 0.0.0.0 --port 5555
   ```
3. Make sure port **5555** is allowed through the firewall.
4. On every other machine:
   ```bash
   python client_final.py --host 192.168.1.10 --port 5555
   ```

---

## 🧩 Wire Protocol

Each frame on the wire:

```
+---------------------+----------------------------+
| length (4 B, !I)    |   JSON payload (UTF-8)     |
+---------------------+----------------------------+
```

Example payloads (actual implementation):

```json
{ "type": "login", "body": "alice" }
{ "type": "list",  "sender": "SERVER", "body": "[\"alice\",\"bob\"]", "timestamp": "20:43:21" }
{ "type": "msg",   "sender": "alice", "to": "ALL", "scope": "group", "body": "hello", "timestamp": "20:43:31" }
{ "type": "msg",   "sender": "alice", "to": "bob", "scope": "dm", "body": "hi bob", "timestamp": "20:44:01" }
{ "type": "info",  "sender": "SERVER", "body": "Welcome, alice!", "timestamp": "20:43:22" }
{ "type": "error", "sender": "SERVER", "body": "User 'bob' not found.", "timestamp": "20:44:10" }
{ "type": "logout" }
```

The 4-byte big-endian length prefix lets the receiver read **exactly** one full
JSON message even when TCP merges or splits packets.

---

## 🏗 Architecture

```
        Client A ─┐
        Client B ─┼──► [ Server ] ──► routes / broadcasts
        Client C ─┘     (per-client thread)
```

- **Server**: 1 acceptor thread + N handler threads. A `dict[str, socket]`
  registry is guarded by a `threading.Lock`. The lock is released **before**
  `sendall()` so a slow recipient cannot freeze the whole server.
- **Client**: 1 Tk main thread + 1 receiver thread. The receiver pushes decoded
  events into a `queue.Queue`; `root.after(30, drain)` consumes them on the UI
  thread, so the GUI never blocks.

---

## 🧪 Testing Checklist

- [x] 3+ concurrent clients on loopback
- [x] Private messages delivered both directions
- [x] Group broadcast reaches all participants
- [x] Abrupt disconnect updates every other client's user list
- [x] Duplicate username rejected with `LOGIN_ERR`
- [x] Long messages (~500 chars) survive framing intact

---

## 🖥 CLI Reference

```
python server.py [--host 0.0.0.0] [--port 5555]
python client_final.py [--host 127.0.0.1] [--port 5555]
python client_final.py --username Ali --host 127.0.0.1 --port 5555
```

---

## 📄 Report

A full project report with architecture diagrams, sequence flow, implementation
notes and deployment instructions can be prepared using **`REPORT_TEMPLATE.md`**.

---

## 👤 Author

`<Your Name — Roll No.>`  
Computer Networks, `<Semester / Year>`
