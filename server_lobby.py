import hashlib
import os
import random
import sqlite3
import sys
import grpc
from concurrent import futures
import time
import queue
import threading
import json
import logging

import lobby_pb2_grpc
import lobby_pb2
import json
import traceback

'''
Making sure the server is started with the correct arguments.
'''

if len(sys.argv) != 2:
    logging.error("Usage: python server_lobby.py <lobby_index>")
    sys.exit(1)

# if it is and the argument is NOT an integer between 0 and 4, exit
if not (0 <= int(sys.argv[1]) <= 4):
    logging.error("Invalid argument. Please enter an integer between 0 and 4")
    sys.exit(1)

idx = int(sys.argv[1])

# import config from config/config.json
if not os.path.exists("config/config.json"):
    logging.error("config.json not found.")
    exit(1)
with open("config/config.json") as f:
    config = json.load(f)

log_path = config["lobbies"]["lobby_log_paths"][idx]
db_path = config["lobbies"]["lobby_db_paths"][idx]

# setup logging
if not os.path.exists(log_path):
    with open(log_path, "w") as f:
        pass

logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

try:
    host = config["lobbies"]["lobby_hosts"][idx]
    port = config["lobbies"]["lobby_ports"][idx]
except KeyError as e:
    logging.error(f"KeyError for config: {e}")
    exit(1)

"""
The following are parameters that the server
needs to keep consistent for Raft
"""
# map of clients to queues for sending responses
clients = {}


class LobbyServiceServicer(lobby_pb2_grpc.LobbyServiceServicer):
    """
    MainServiceServicer class for MainServiceServicer

    This class handles the main chat functionality of the server, sending responses via queues.
    All log messages in this service begin with [MAIN].
    """

    def Lobby(self, request_iterator, context):
        """
        Chat function for ChatServiceServicer, unique to each client.

        Parameters:
        ----------
        request_iterator : iterator
            iterator of requests from client
        context : context
            All tutorials have this, but it's not used here. Kept for compatibility.
        """
        username = None
        # queue for sending responses to client
        client_queue = queue.Queue()

        # handle incoming requests
        def handle_requests():
            global log, current_term
            nonlocal username
            try:
                for req in request_iterator:
                    # print size of req in bytes
                    logging.info(f"[MAIN] Size of request: {sys.getsizeof(req)} bytes")
                    # log the request
                    logging.info(f"[MAIN] Received request: {req}")

                    if req.action == lobby_pb2.JOIN_LOBBY:
                        logging.info(f"[MAIN] {req.username} connected.")
                        if (req.username != "") and (req.username not in clients):
                            clients[req.username] = client_queue
                            username = req.username
                        client_queue.put(
                            lobby_pb2.LobbyResponse(
                                action=lobby_pb2.JOIN_LOBBY, result=True
                            )
                        )
                    else:
                        logging.error(f"[MAIN] Invalid action: {req.action}")
            except Exception as e:
                tb = traceback.extract_tb(e.__traceback__)
                line_number = tb[-1].lineno if tb else "unknown"
                logging.error(
                    f"[MAIN] Error handling requests at line {line_number}: {traceback.format_exc()}"
                )
                print(f"[MAIN] Error handling requests at line {line_number}: {traceback.format_exc()}")
            finally:
                if username in clients:
                    del clients[username]
                    logging.info(f"[MAIN] {username} disconnected.")

        # run request handling in a separate thread.
        threading.Thread(target=handle_requests, daemon=True).start()

        # continuously yield responses from the client's queue.
        while True:
            try:
                response = client_queue.get()
                yield response
            except Exception as e:
                break

def serve():
    """
    Main loop for lobby server. Runs server on separate thread.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    lobby_pb2_grpc.add_LobbyServiceServicer_to_server(LobbyServiceServicer(), server)
    print(f"{host}:{port}")
    server.add_insecure_port(f"{host}:{port}")
    server.start()

    logging.info(f"[SETUP] Lobby server started on port {port}")
    # wait for random time from 1 to 5 seconds before starting, to allow one server to become leader
    time.sleep(2 * random.random())
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    serve()
