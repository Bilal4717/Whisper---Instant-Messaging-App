# Instant Messaging System — Technical Report (Template)

**Course**: Computer Communication Networks (CCN)  
**Project**: Instant Messaging (Client–Server using TCP sockets)  
**Deadline**: 08 May 2026  

## (i) Project Introduction

- **Background**: Briefly explain instant messaging and why TCP sockets are used for reliable delivery.
- **Motivation**: What the prototype demonstrates (client-server routing, concurrency, GUI, real-time updates).
- **Scope**:
  - In-scope: text messaging, one-to-one (DM) and group chat via central server, username login, GUI, TCP.
  - Out-of-scope: voice/video, encryption, message history persistence (unless you implemented it).

## (ii) System Architecture

Insert a labeled diagram showing clients ↔ server over TCP and how messages flow.

- **Architecture diagram**: (paste your image here)
  - Suggested caption: *Figure 1: Client–Server IM Architecture*

## (iii) Design & Components

### Protocol design (application-layer over TCP)

Describe your message framing/serialization.

- **Transport**: TCP stream (reliable, ordered).
- **Serialization**: JSON objects.
- **Framing**: newline-terminated packets (`\\n`) so the receiver can detect message boundaries even with partial reads.

Document the packet fields you use.

- `type`: `login | msg | list | info | error`
- `sender`: username (server fills this for outgoing deliveries)
- `to`: destination username or `ALL` (client → server)
- `body`: message text (or JSON-encoded list for `list`)
- `timestamp`: server-generated time for display

### Data structures

- Server-side: `clients: dict[username -> socket]` protected by a lock for concurrency.
- Client-side: online user list in the GUI; selected target for DM vs group.

### Threading model

- **Server**: one thread per connected client (`handle_client`) to support concurrent users.
- **Client**: background receiver thread so the GUI event loop never blocks on `recv()`.

## (iv) Workflow (Sequence / Flowchart)

Add a sequence diagram (can be drawn in Word/Google Docs) for:

1. Client connects
2. Client sends `login`
3. Server registers username and broadcasts join + user list
4. Messaging:
   - Group: client sends `{type:"msg", to:"ALL", body:"..."}` → server broadcasts to all
   - DM: client sends `{type:"msg", to:"<user>", body:"..."}` → server routes to the target and echoes to sender

## (v) Implementation Details

Explain what socket APIs you used and why:

- Server: `socket()`, `bind()`, `listen()`, `accept()`, `recv()`, `sendall()`
- Client: `socket()`, `connect()`, `recv()`, `sendall()`

Explain key challenges and how you solved them:

- **TCP is a stream**: solved with newline framing + buffering and looped parsing.
- **Non-blocking UI**: solved with a receiver thread + GUI updates scheduled on the main thread.
- **Concurrent clients**: server threads + shared state protected by a lock.

## (vi) Testing (with screenshots)

Provide screenshots showing:

- Server console running.
- **At least two clients** logged in with different usernames.
- Messages exchanged:
  - A group message received by both clients.
  - A DM sent to one user (optional but recommended).

## (vii) Deployment Instructions

### Localhost (single machine)

1. Run server:
   - `python server.py`
2. Run 2–3 clients in separate terminals:
   - `python client.py`
3. Use host `127.0.0.1` and port `5555`.

### Across two machines (same LAN / internet)

1. Start server on machine A.
2. Ensure firewall allows inbound TCP `5555`.
3. On machine B, run client and set host to machine A’s IP (e.g., `192.168.x.x`).

## (viii) Conclusion

Summarize what works, what was learned (TCP, sockets, threading, GUI), and possible future improvements.

## (ix) Appendix — Source Code

Attach `server.py` and `client.py` as-is (your submission requires `.py` source).

