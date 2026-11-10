# -*- coding: utf-8 -*-
"""Socket listener for Quixel Bridge / Epic Fab live links.

Both apps open a TCP connection, write one JSON payload and close it. We
read until EOF and hand the bytes to a callback. Quixel Bridge stops the
listener with b"Bye Megascans"; the Fab launcher probes the target with
b"ping" (we answer with the plugin version, in the same pseudo-dict format
Epic's own DCC plugins use) and says goodbye with b"Bye Fab" (ignored - the
listener stays up so the target can be re-enabled without a restart).
"""
import json
import socket
import threading

from . import logger

STOP_MESSAGE = b"Bye Megascans"
FAB_BYE_MESSAGE = b"Bye Fab"
PING_MESSAGE = b"ping"


def split_json_documents(text):
    """Bridge sends one array per connection, but be tolerant of
    several concatenated documents."""
    decoder = json.JSONDecoder()
    index, docs = 0, []
    text = text.strip()
    while index < len(text):
        while index < len(text) and text[index] in " \r\n\t\x00":
            index += 1
        if index >= len(text):
            break
        doc, end = decoder.raw_decode(text, index)
        docs.append(doc)
        index = end
    return docs


class BridgeServer(object):
    def __init__(self, host, port, on_payload, plugin_version=""):
        self.host = host
        self.port = int(port)
        self.on_payload = on_payload
        self.plugin_version = str(plugin_version or "")
        self._sockets = []
        self._threads = []
        self._running = threading.Event()

    @property
    def running(self):
        return self._running.is_set()

    def start(self):
        if self.running:
            return True
        addresses = [(socket.AF_INET, self.host)]
        if self.host in ("127.0.0.1", "localhost") and socket.has_ipv6:
            addresses.append((socket.AF_INET6, "::1"))   # Bridge may resolve localhost to ::1
        for family, host in addresses:
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind((host, self.port))
                sock.listen(5)
                sock.settimeout(1.0)
            except OSError as error:
                sock.close()
                if family == socket.AF_INET:
                    logger.error("cannot listen on %s:%d (%s). Is another Sandbox/Blender using it?"
                                 % (host, self.port, error))
                    self.stop()
                    return False
                continue
            self._sockets.append(sock)
        self._running.set()
        for sock in self._sockets:
            thread = threading.Thread(target=self._accept_loop, args=(sock,), name="qceb-listen", daemon=True)
            thread.start()
            self._threads.append(thread)
        logger.info("listening for Quixel Bridge / Fab on %s:%d" % (self.host, self.port))
        return True

    def stop(self):
        self._running.clear()
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass
        self._sockets = []
        self._threads = []

    def _accept_loop(self, sock):
        while self._running.is_set():
            try:
                client, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), name="qceb-client", daemon=True).start()

    def _send_ping_reply(self, client):
        """Fab handshake: same reply format Epic's DCC plugins send."""
        if not self.plugin_version:
            return
        try:
            client.sendall(str.encode("{'plugin_version': '%s'}" % self.plugin_version))
        except OSError:
            pass

    def _handle(self, client):
        chunks = []
        try:
            client.settimeout(30.0)
            while True:
                data = client.recv(65536)
                if not data:
                    break
                if not chunks and data.strip() in (PING_MESSAGE, b""):
                    # Fab probe; the payload may follow on this connection
                    self._send_ping_reply(client)
                    continue
                chunks.append(data)
        except socket.timeout:
            logger.warning("connection timed out; using received data")
        except OSError as error:
            logger.warning("connection error: %s" % error)
        finally:
            try:
                client.close()
            except OSError:
                pass
        payload = b"".join(chunks)
        if not payload:
            return
        if payload.strip() == STOP_MESSAGE:
            logger.info("stop message received")
            self.stop()
            return
        if payload.strip() == FAB_BYE_MESSAGE:
            logger.info("Fab disconnect message received; listener stays up")
            return
        try:
            self.on_payload(payload)
        except Exception as error:  # noqa
            logger.error("failed to queue payload: %s" % error)
