import socket
import json
import struct
import threading
import time
import os
import queue
from dataclasses import dataclass
from typing import Callable, Optional

DISCOVERY_PORT = 9876
TCP_PORT = 9877
BROADCAST_ADDR = "255.255.255.255"
BUFFER_SIZE = 65536
CHUNK_SIZE = 32768
DISCOVERY_INTERVAL = 3
PEER_TIMEOUT = 12


@dataclass
class Peer:
    name: str
    ip: str
    last_seen: float = 0.0
    online: bool = True

    @property
    def display_name(self):
        return f"{self.name} ({self.ip})"


@dataclass
class ChatMessage:
    sender: str
    content: str
    timestamp: float = 0.0
    is_file: bool = False
    file_name: str = ""
    file_size: int = 0
    file_path: str = ""
    is_self: bool = False


class NetworkManager:
    def __init__(
        self,
        username: str,
        on_message: Callable,
        on_file_progress: Callable,
        on_peers_changed: Callable,
    ):
        self.username = username
        self.on_message = on_message
        self.on_file_progress = on_file_progress
        self.on_peers_changed = on_peers_changed

        self.peers: dict[str, Peer] = {}
        self.peers_lock = threading.Lock()

        self.running = True
        self.udp_sock: Optional[socket.socket] = None
        self.tcp_server: Optional[socket.socket] = None

        self.msg_queue = queue.Queue()

    def start(self):
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.settimeout(1.0)
        try:
            self.udp_sock.bind(("0.0.0.0", DISCOVERY_PORT))
        except OSError:
            self.udp_sock.close()
            self.udp_sock = None

        if self.udp_sock:
            threading.Thread(target=self._udp_listener, daemon=True, name="udp-listen").start()
        threading.Thread(target=self._udp_broadcaster, daemon=True, name="udp-broadcast").start()
        threading.Thread(target=self._tcp_server_thread, daemon=True, name="tcp-server").start()
        threading.Thread(target=self._queue_processor, daemon=True, name="queue-proc").start()

    def stop(self):
        self.running = False
        self._close_socket(self.udp_sock)
        self._close_socket(self.tcp_server)

    def _close_socket(self, sock):
        if sock:
            try:
                sock.close()
            except:
                pass

    def _udp_listener(self):
        while self.running:
            try:
                data, addr = self.udp_sock.recvfrom(BUFFER_SIZE)
                msg = json.loads(data.decode("utf-8"))
                if msg.get("type") == "hello" and msg.get("name") != self.username:
                    peer_name = msg["name"]
                    peer_ip = addr[0]
                    now = time.time()
                    with self.peers_lock:
                        if peer_ip not in self.peers:
                            self.peers[peer_ip] = Peer(name=peer_name, ip=peer_ip, last_seen=now, online=True)
                        else:
                            self.peers[peer_ip].last_seen = now
                            self.peers[peer_ip].online = True
                            if self.peers[peer_ip].name != peer_name:
                                self.peers[peer_ip].name = peer_name
                    self.on_peers_changed()
            except socket.timeout:
                continue
            except Exception:
                continue

    def _udp_broadcaster(self):
        time.sleep(0.5)
        msg = json.dumps({"type": "hello", "name": self.username}).encode("utf-8")
        while self.running:
            if self.udp_sock:
                try:
                    self.udp_sock.sendto(msg, (BROADCAST_ADDR, DISCOVERY_PORT))
                except:
                    pass
            for _ in range(DISCOVERY_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)
            now = time.time()
            changed = False
            with self.peers_lock:
                for peer in list(self.peers.values()):
                    if peer.online and now - peer.last_seen > PEER_TIMEOUT:
                        peer.online = False
                        changed = True
            if changed:
                self.on_peers_changed()

    def _tcp_server_thread(self):
        self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_server.settimeout(1.0)
        try:
            self.tcp_server.bind(("0.0.0.0", TCP_PORT))
            self.tcp_server.listen(5)
        except OSError as e:
            self.tcp_server = None
            return
        while self.running:
            try:
                conn, addr = self.tcp_server.accept()
                threading.Thread(
                    target=self._handle_tcp_client,
                    args=(conn, addr[0]),
                    daemon=True,
                    name=f"tcp-handle-{addr[0]}",
                ).start()
            except socket.timeout:
                continue
            except:
                continue

    def _handle_tcp_client(self, conn: socket.socket, peer_ip: str):
        try:
            conn.settimeout(10.0)
            length_buf = conn.recv(4)
            conn.settimeout(None)
            if not length_buf or len(length_buf) < 4:
                return
            msg_len = struct.unpack("<I", length_buf)[0]
            data = b""
            while len(data) < msg_len:
                chunk = conn.recv(min(msg_len - len(data), BUFFER_SIZE))
                if not chunk:
                    break
                data += chunk
            header = json.loads(data.decode("utf-8"))
            msg_type = header.get("type")

            if msg_type == "msg":
                msg = ChatMessage(
                    sender=header.get("sender", "Unknown"),
                    content=header.get("content", ""),
                    timestamp=header.get("time", time.time()),
                    is_file=False,
                )
                self.msg_queue.put(("msg", msg, peer_ip))

            elif msg_type == "file_offer":
                file_name = header.get("name", "unknown")
                file_size = header.get("size", 0)
                sender = header.get("sender", "Unknown")
                ts = header.get("time", time.time())
                recv_dir = os.path.join(os.path.expanduser("~"), "Downloads", "LanChat")
                os.makedirs(recv_dir, exist_ok=True)
                base, ext = os.path.splitext(file_name)
                file_path = os.path.join(recv_dir, file_name)
                counter = 1
                while os.path.exists(file_path):
                    file_path = os.path.join(recv_dir, f"{base}({counter}){ext}")
                    counter += 1
                conn.sendall(b"\x01")
                received = 0
                with open(file_path, "wb") as f:
                    while received < file_size:
                        remaining = file_size - received
                        read_size = min(CHUNK_SIZE, remaining)
                        chunk = conn.recv(read_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        progress = int(received / file_size * 100)
                        self.msg_queue.put(
                            ("file_progress", progress, file_name, sender, peer_ip)
                        )
                msg = ChatMessage(
                    sender=sender,
                    content="",
                    timestamp=ts,
                    is_file=True,
                    file_name=file_name,
                    file_size=file_size,
                    file_path=file_path,
                )
                self.msg_queue.put(("msg", msg, peer_ip))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except:
                pass

    def _queue_processor(self):
        while self.running:
            try:
                item = self.msg_queue.get(timeout=0.5)
                if item[0] == "msg":
                    _, msg, peer_ip = item
                    self.on_message(msg, peer_ip)
                elif item[0] == "file_progress":
                    self.on_file_progress(*item[1:])
            except queue.Empty:
                pass
            except:
                pass

    def send_message(self, peer_ip: str, content: str) -> bool:
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.settimeout(10.0)
            conn.connect((peer_ip, TCP_PORT))
            header = json.dumps({
                "type": "msg",
                "sender": self.username,
                "content": content,
                "time": time.time(),
            }).encode("utf-8")
            conn.sendall(struct.pack("<I", len(header)) + header)
            conn.close()
            return True
        except Exception:
            return False

    def send_file(self, peer_ip: str, file_path: str) -> bool:
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.settimeout(60.0)
            conn.connect((peer_ip, TCP_PORT))
            header = json.dumps({
                "type": "file_offer",
                "sender": self.username,
                "name": file_name,
                "size": file_size,
                "time": time.time(),
            }).encode("utf-8")
            conn.sendall(struct.pack("<I", len(header)) + header)
            ack = conn.recv(1)
            if ack != b"\x01":
                conn.close()
                return False
            sent = 0
            with open(file_path, "rb") as f:
                while sent < file_size:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    conn.sendall(chunk)
                    sent += len(chunk)
                    progress = int(sent / file_size * 100)
                    self.msg_queue.put(
                        ("file_progress", progress, file_name, self.username, peer_ip)
                    )
            conn.close()
            msg = ChatMessage(
                sender=self.username,
                content="",
                timestamp=time.time(),
                is_file=True,
                file_name=file_name,
                file_size=file_size,
                file_path=file_path,
                is_self=True,
            )
            self.msg_queue.put(("msg", msg, peer_ip))
            return True
        except Exception:
            return False
