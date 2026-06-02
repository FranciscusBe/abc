#!/usr/bin/env python3
import socket, threading, argparse, select, logging, os
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)
BUFFER_SIZE = 8192
TIMEOUT = 30

def recv_request(sock):
    data = b""
    while b"\r\n\r\n" not in data:
        try:
            chunk = sock.recv(BUFFER_SIZE)
            if not chunk:
                break
            data += chunk
        except socket.timeout:
            break
    return data

def handle_connect(client_sock, target):
    parts = target.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 443
    server_sock = None
    try:
        server_sock = socket.create_connection((host, port), timeout=TIMEOUT)
        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        client_sock.settimeout(TIMEOUT)
        socks = [client_sock, server_sock]
        while True:
            rlist, _, xlist = select.select(socks, [], socks, TIMEOUT)
            if xlist or not rlist:
                break
            closed = False
            for sock in rlist:
                other = server_sock if sock is client_sock else client_sock
                try:
                    data = sock.recv(BUFFER_SIZE)
                    if not data:
                        closed = True
                        break
                    other.sendall(data)
                except Exception:
                    closed = True
                    break
            if closed:
                break
    except Exception as e:
        logger.error(f"CONNECT to {host}:{port} failed: {e}")
        try:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except Exception:
            pass
    finally:
        if server_sock:
            server_sock.close()

def handle_client(client_sock, client_addr):
    logger.info(f"New connection from {client_addr}")
    server_sock = None
    try:
        request = recv_request(client_sock)
        if not request:
            return
        lines = request.split(b"\r\n")
        first = lines[0].decode("utf-8", errors="ignore")
        parts = first.split(" ")
        if len(parts) < 2:
            return
        method = parts[0].upper()
        url = parts[1]

        if method == "CONNECT":
            handle_connect(client_sock, url)
            return

        if url.startswith("http://"):
            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port or 80
            path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
            lines[0] = f"{method} {path} HTTP/1.1".encode()
            new_request = b"\r\n".join(lines)
        else:
            host, port = None, 80
            for line in lines[1:]:
                if line.lower().startswith(b"host:"):
                    hp = line.split(b":", 1)[1].strip().decode()
                    if ":" in hp:
                        host, port = hp.rsplit(":", 1)
                        port = int(port)
                    else:
                        host = hp
                    break
            if not host:
                client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            new_request = request

        logger.info(f"  >> {method} {host}:{port}")
        try:
            server_sock = socket.create_connection((host, port), timeout=TIMEOUT)
            server_sock.sendall(new_request)
            while True:
                data = server_sock.recv(BUFFER_SIZE)
                if not data:
                    break
                client_sock.sendall(data)
        except ConnectionRefusedError as e:
            logger.error(f"Connection refused to {host}:{port} - {e}")
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except socket.timeout:
            client_sock.sendall(b"HTTP/1.1 504 Gateway Timeout\r\n\r\n")
        except Exception as e:
            logger.error(f"Error forwarding to {host}:{port} - {e}")
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
    except Exception as e:
        logger.error(f"Error handling {client_addr}: {e}")
    finally:
        if server_sock:
            server_sock.close()
        client_sock.close()
        logger.info(f"Connection closed from {client_addr}")

def start_proxy(port, bind="0.0.0.0"):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((bind, port))
    server_sock.listen(100)
    logger.info(f"Proxy listening on {bind}:{port}")
    try:
        while True:
            client_sock, client_addr = server_sock.accept()
            client_sock.settimeout(TIMEOUT)
            threading.Thread(target=handle_client, args=(client_sock, client_addr), daemon=True).start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        server_sock.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()
    start_proxy(args.port, args.bind)
