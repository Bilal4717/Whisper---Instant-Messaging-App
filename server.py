"""
server.py — Instant Messaging Server
Handles client registration, message routing, and concurrent connections.
Uses TCP sockets + multi-threading to support group chat among multiple users.
"""

import os
import socket
import threading
import json
import datetime
import sys
import traceback
import argparse
import struct

# ─── Configuration ───────────────────────────────────────────────────────────
HOST = "0.0.0.0"   # Listen on all interfaces
PORT = 5555        # Port clients will connect to
BUFFER = 4096      # Max bytes per receive call

# ─── Shared State (protected by a lock) ──────────────────────────────────────
clients_lock = threading.Lock()
clients: dict[str, socket.socket] = {}   # username -> socket


# ─── Helpers ─────────────────────────────────────────────────────────────────

def build_packet(sender: str, body: str, msg_type: str = "msg", **extra) -> dict:
    """Build a structured message packet (dict)."""
    packet: dict = {
        "type":      msg_type,          # msg | info | error | list
        "sender":    sender,
        "body":      body,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
    }
    if extra:
        packet.update(extra)
    return packet


def encode_frame(packet: dict) -> bytes:
    """Length-prefixed framing: 4-byte big-endian length + UTF-8 JSON payload."""
    payload = json.dumps(packet, ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


def send_to(sock: socket.socket, packet: dict) -> bool:
    """Send a framed packet to a socket; return False on failure."""
    try:
        sock.sendall(encode_frame(packet))
        return True
    except OSError as e:
        print(f"[SERVER] send failed: {e}", flush=True)
        return False


def broadcast(sender: str, body: str, exclude: str | None = None):
    """Send a message to every connected user except `exclude`."""
    packet = build_packet(sender, body)
    # Never call send_to while holding clients_lock — TCP send can block if a client stops reading.
    with clients_lock:
        targets = [(u, s) for u, s in list(clients.items()) if u != exclude]
    for _uname, sock in targets:
        send_to(sock, packet)


def _snapshot_usernames() -> list[str]:
    with clients_lock:
        return list(clients.keys())


def send_user_list(sock: socket.socket):
    """Push the current online-user list to a specific socket."""
    online = _snapshot_usernames()
    packet = build_packet("SERVER", json.dumps(online), msg_type="list")
    send_to(sock, packet)


def remove_client(username: str):
    """Unregister a client and notify others."""
    with clients_lock:
        clients.pop(username, None)
        print(f"[SERVER] '{username}' disconnected. Online: {list(clients.keys())}", flush=True)
    broadcast("SERVER", f"{username} has left the chat.")
    # Refresh user list for everyone (must not nest clients_lock around send_user_list)
    with clients_lock:
        socks = list(clients.values())
    for sock in socks:
        send_user_list(sock)


# ─── Per-client thread ────────────────────────────────────────────────────────

def handle_client(conn: socket.socket, addr: tuple):
    """
    Runs in its own thread for each connected client.
    Protocol:
      1. First message from client must be {"type":"login","body":"<username>"}
      2. Subsequent messages: {"type":"msg","to":"<user|ALL>","body":"..."}
    """
    username = None
    inbuf = bytearray()

    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass

    try:
        # ── Step 1: Login handshake (length-prefixed JSON) ───────────────────
        # Read until we have at least one full frame.
        while True:
            if len(inbuf) >= 4:
                msg_len = struct.unpack("!I", inbuf[:4])[0]
                if len(inbuf) >= 4 + msg_len:
                    payload = bytes(inbuf[4:4 + msg_len])
                    del inbuf[:4 + msg_len]
                    try:
                        pkt = json.loads(payload.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        send_to(conn, build_packet("SERVER", "Invalid login packet (bad JSON).", "error"))
                        conn.close()
                        return
                    break

            chunk = conn.recv(BUFFER)
            if not chunk:
                conn.close()
                return
            inbuf.extend(chunk)

        if pkt.get("type") != "login":
            send_to(conn, build_packet("SERVER", "Expected login packet.", "error"))
            conn.close()
            return

        username = str(pkt.get("body", "")).strip()
        if not username:
            send_to(conn, build_packet("SERVER", "Username cannot be empty.", "error"))
            conn.close()
            return

        with clients_lock:
            duplicate = username in clients
            if not duplicate:
                clients[username] = conn
        if duplicate:
            send_to(conn, build_packet("SERVER",
                    "Username already taken. Please reconnect with a different name.",
                    "error"))
            conn.close()
            return

        print(f"[SERVER] '{username}' connected from {addr}. Online: {list(clients.keys())}", flush=True)
        if not send_to(conn, build_packet("SERVER", f"Welcome, {username}! You are now connected.", "info")):
            with clients_lock:
                clients.pop(username, None)
            print(f"[SERVER] Welcome packet failed for '{username}'; closing without notifying others.", flush=True)
            username = None  # Skip remove_client() — user was never fully online
            return
        broadcast("SERVER", f"{username} joined the chat.", exclude=username)

        # Push updated user list to everyone (do not nest clients_lock around send_user_list)
        with clients_lock:
            socks = list(clients.values())
        for sock in socks:
            send_user_list(sock)

        # ── Step 2: Message loop (length-prefixed frames) ────────────────────
        while True:
            # Drain all complete frames currently in the buffer.
            while len(inbuf) >= 4:
                msg_len = struct.unpack("!I", inbuf[:4])[0]
                if len(inbuf) < 4 + msg_len:
                    break
                payload = bytes(inbuf[4:4 + msg_len])
                del inbuf[:4 + msg_len]
                try:
                    msg = json.loads(payload.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue

                mtype = msg.get("type", "msg")
                body = msg.get("body", "")
                if isinstance(body, str):
                    body = body.strip()
                to = msg.get("to", "ALL")

                if mtype == "logout":
                    # Graceful disconnect requested by client.
                    return

                if mtype == "msg":
                    if to == "ALL":
                        # Broadcast to everyone (including sender for echo)
                        # Include `to`/`scope` metadata for clients (harmless for older clients).
                        packet = build_packet(
                            sender=username,
                            body=str(body),
                            msg_type="msg",
                            scope="group",
                            to="ALL",
                        )
                        with clients_lock:
                            targets = list(clients.values())
                        for s in targets:
                            send_to(s, packet)
                        print(f"[BROADCAST] {username}: {body}", flush=True)
                    else:
                        # Private / direct message
                        with clients_lock:
                            target_sock = clients.get(to)

                        if target_sock:
                            # Include metadata so clients can build a better DM UX.
                            pm_packet = build_packet(
                                sender=username,
                                body=str(body),
                                msg_type="msg",
                                scope="dm",
                                to=to,
                            )
                            send_to(target_sock, pm_packet)
                            # Echo back to sender
                            send_to(conn, pm_packet)
                            print(f"[PRIVATE] {username} -> {to}: {body}", flush=True)
                        else:
                            send_to(conn, build_packet("SERVER",
                                    f"User '{to}' not found.", "error"))

            chunk = conn.recv(BUFFER)
            if not chunk:
                break   # Client disconnected
            inbuf.extend(chunk)

    except (ConnectionResetError, OSError):
        pass
    except Exception:
        print(f"[SERVER] Unhandled error for {addr}:", flush=True)
        traceback.print_exc()
    finally:
        if username:
            remove_client(username)
        try:
            conn.close()
        except OSError:
            pass


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Instant Messaging Server")
    parser.add_argument("--host", default=HOST, help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=PORT, help="Bind port (default: 5555)")
    args = parser.parse_args()

    host = args.host
    port = args.port

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Windows: SO_REUSEADDR allows multiple listeners on the same port in some setups,
    # which leads to “ghost” servers — clients connect to a different PID than your terminal.
    # Exclusive binding prevents a second server.py from stealing the same port.
    if sys.platform == "win32":
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind((host, port))
    except OSError as e:
        print(f"[SERVER] Cannot bind {host}:{port} — {e}", flush=True)
        print(
            "[SERVER] Port is already in use. Close the other python server.py "
            "(or stop the Python process listening on this port), then try again.",
            flush=True,
        )
        sys.exit(1)
    server_sock.listen(10)
    print(f"[SERVER] PID {os.getpid()} — Listening on {host}:{port}  (Ctrl-C to stop)", flush=True)

    try:
        while True:
            conn, addr = server_sock.accept()
            print(f"[SERVER] Accepted TCP connection from {addr}", flush=True)
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down.", flush=True)
    finally:
        server_sock.close()


if __name__ == "__main__":
    main()
