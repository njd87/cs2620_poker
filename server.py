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

import main_pb2_grpc
import main_pb2
import raft_pb2_grpc
import raft_pb2
import lobby_pb2_grpc
import lobby_pb2
import json
import traceback
from replica_helpers import replicate_action

'''
Making sure the server is started with the correct arguments.
'''
num_servers = 2

if len(sys.argv) != 2:
    logging.error("Usage: python server.py <server_index>")
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

log_path = config["servers"]["log_paths"][idx]
db_path = config["servers"]["db_paths"][idx]

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
    host = config["servers"]["hosts"][idx]
    port = config["servers"]["ports"][idx]
except KeyError as e:
    logging.error(f"KeyError for config: {e}")
    exit(1)

"""
The following are parameters that the server
needs to keep consistent for Raft
"""
# map of clients to queues for sending responses
clients = {}

# get names of all servers
all_servers = [
    f"{config['servers']['hosts'][i]}:{config['servers']['ports'][i]}"
    for i in range(num_servers)
    if i != idx
]

# raft params
raft_state = "FOLLOWER"
current_term = 0
voted_for = None
log = []
leader_address = None
rec_votes = 0
num_servers = len(all_servers) + 1
# timer for election timeout
timer = random.randint(1, 5)
commit = 0

class MainServiceServicer(main_pb2_grpc.MainServiceServicer):
    """
    MainServiceServicer class for MainServiceServicer

    This class handles the main chat functionality of the server, sending responses via queues.
    All log messages in this service begin with [MAIN].
    """

    def Main(self, request_iterator, context):
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
        # indicator for whether the server is connected to a lobby or a client
        connected_to_lobby = False
        # queue for sending responses to client
        client_queue = queue.Queue()
        # queue for sending responses to lobby
        lobby_queue = queue.Queue()

        # handle incoming requests
        def handle_requests():
            global log, current_term
            nonlocal username, connected_to_lobby
            try:
                for req in request_iterator:
                    # print size of req in bytes
                    logging.info(f"[MAIN] Size of request: {sys.getsizeof(req)} bytes")
                    # create a copy of req with different memory
                    log_copy = raft_pb2.LogEntry(
                        action=req.action,
                        username=req.username,
                        passhash=req.passhash,
                        money_to_add=req.money_to_add,
                        game_type=req.game_type,
                        term=current_term,
                    )
                    log.append(log_copy)

                    if req.action == main_pb2.CHECK_USERNAME:
                        # check if username is already in use
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        sqlcur.execute(
                            "SELECT * FROM users WHERE username=?", (req.username,)
                        )

                        # if username is already in use, send response with success=False
                        # otherwise, send response with success=True
                        if sqlcur.fetchone():
                            client_queue.put(
                                main_pb2.MainResponse(
                                    action=main_pb2.CHECK_USERNAME, result=False
                                )
                            )
                        else:
                            client_queue.put(
                                main_pb2.MainResponse(
                                    action=main_pb2.CHECK_USERNAME, result=True
                                )
                            )
                        sqlcon.close()

                    elif req.action == main_pb2.LOGIN:
                        # check if username and password match
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        new_passhash = hashlib.sha256(req.passhash.encode()).hexdigest()

                        sqlcur.execute(
                            "SELECT * FROM users WHERE username=? AND passhash=?",
                            (req.username, new_passhash),
                        )

                        # if username and password match, send response with success=True
                        # otherwise, send response with success=False
                        if sqlcur.fetchone():

                            sqlcur.execute(
                                "SELECT moolah FROM users WHERE username=?",
                                (req.username,),
                            )

                            moolah = sqlcur.fetchone()[0]

                            response = main_pb2.MainResponse(
                                action=main_pb2.LOGIN,
                                result=True,
                                moolah=moolah,
                            )

                            client_queue.put(response)

                            # add user to clients
                            username = req.username
                            clients[username] = client_queue
                        else:
                            client_queue.put(
                                main_pb2.MainResponse(
                                    action=main_pb2.LOGIN, result=False
                                )
                            )
                        sqlcon.close()

                    elif req.action == main_pb2.REGISTER:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        # check to make sure username is not already in use
                        sqlcur.execute(
                            "SELECT * FROM users WHERE username=?", (req.username,)
                        )
                        if sqlcur.fetchone():
                            client_queue.put(
                                main_pb2.MainResponse(
                                    action=main_pb2.REGISTER, result=False
                                )
                            )
                        else:
                            # add new user to database
                            new_passhash = hashlib.sha256(
                                req.passhash.encode()
                            ).hexdigest()
                            sqlcur.execute(
                                "INSERT INTO users (username, passhash) VALUES (?, ?)",
                                (req.username, new_passhash),
                            )
                            sqlcon.commit()
                            response = main_pb2.MainResponse(
                                action=main_pb2.REGISTER,
                                result=True,
                                moolah = 500
                            )

                            client_queue.put(response)

                        sqlcon.close()

                        # add user to clients
                        username = req.username
                        clients[username] = client_queue

                    elif req.action == main_pb2.DELETE_ACCOUNT:
                        # delete account if params match
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        username = req.username
                        passhash = req.passhash

                        passhash = hashlib.sha256(passhash.encode()).hexdigest()
                        sqlcur.execute(
                            "SELECT passhash FROM users WHERE username=?", (username,)
                        )

                        result = sqlcur.fetchone()
                        if result:
                            # username exists and passhash matches
                            if result[0] == passhash:
                                sqlcur.execute(
                                    "DELETE FROM users WHERE username=?", (username,)
                                )
                                sqlcon.commit()

                                client_queue.put(
                                    main_pb2.MainResponse(
                                        action=main_pb2.DELETE_ACCOUNT, result=True
                                    )
                                )
                                # tell server to ping users to update their chat, remove from connected users

                                # delete user from clients
                                if username in clients:
                                    del clients[username]

                            # username exists but passhash is wrong
                            else:
                                client_queue.put(
                                    main_pb2.MainResponse(
                                        action=main_pb2.DELETE_ACCOUNT, result=False
                                    )
                                )
                        else:
                            # username doesn't exist
                            client_queue.put(
                                main_pb2.MainResponse(
                                    action=main_pb2.DELETE_ACCOUNT, result=False
                                )
                            )

                        sqlcon.close()
                    elif req.action == main_pb2.CONNECT:
                        # a new leader was chosen, client connected to new leader
                        # add the user to the clients if they are signed in
                        logging.info(f"[MAIN] {req.username} connected.")
                        if (req.username != "") and (req.username not in clients):
                            clients[req.username] = client_queue
                    elif req.action == main_pb2.JOIN_LOBBY:
                        # disconnect from current server
                        logging.info(f"[MAIN] {req.username} joining lobby.")
                        # KG: can add logic to return open lobby
                        client_queue.put(
                            main_pb2.MainResponse(
                                action=main_pb2.JOIN_LOBBY, result=True
                            )
                        )
                    elif req.action == main_pb2.CONNECT_LOBBY:
                        logging.info(f"[MAIN] Lobby {req.username} connected.")
                        if (req.username != "") and (req.username not in clients):
                            clients[req.username] = client_queue
                            connected_to_lobby = True
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
                    if connected_to_lobby:
                        logging.info(f"[MAIN] Lobby {username} disconnected.")
                    else:
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


class RaftServiceServicer(raft_pb2_grpc.RaftServiceServicer):
    """
    RaftServiceServicer class that allows servers to communicate with each other for deciding
    leader and replicating logs. All log messages in this service begin with [RAFT].
    """

    def Vote(self, request, context):
        """
        Handles VoteRequest RPC.

        Parameters:
        ----------
        request : raft_pb2.VoteRequest
            request object from client
        """
        global current_term, voted_for, leader_address, raft_state, timer

        logging.info(
            f"[RAFT] Received VoteRequest: term={request.term}, candidate_id={request.candidate_id}, "
            f"last_log_index={request.last_log_index}, last_log_term={request.last_log_term}"
        )

        # if the candidate's term is less than the current term, reject the vote
        if (request.term < current_term) or (voted_for is None):
            response = raft_pb2.VoteResponse(term=current_term, vote_granted=False)
            return response

        # if the candidate's term is greater than the current term, update the current term and vote for the candidate
        if request.term >= current_term:
            current_term = request.term
            voted_for = request.candidate_id
            response = raft_pb2.VoteResponse(term=current_term, vote_granted=True)
            # leader_address = None
            return response

    def AppendEntries(self, request, context):
        """
        Handles AppendEntriesRequest RPC.
        Replicates log entries and updates the leader.

        Parameters:
        ----------
        request : raft_pb2.AppendEntriesRequest
            request object from client
        """
        global timer, log, current_term, leader_address, raft_state, commit, db_path, voted_for
        logging.info(
            f"[RAFT] Received AppendEntriesRequest: term={request.term}, leader_address={request.leader_address}, "
            f"most_recent_log_idx={request.most_recent_log_idx}, term_of_recent_log={request.term_of_recent_log}, "
            f"leader_commit={request.leader_commit}"
        )
        voted_for = None
        # update timer
        timer = time.time() + random.uniform(0.3, 0.5)

        if raft_state == "LEADER":
            logging.info(f"[RAFT] Lost majority. Server {idx} is leader.")
        raft_state = "FOLLOWER"

        # update leader address if it has changed
        if leader_address != request.leader_address:
            logging.info(
                f"[RAFT] Leader address changed from {leader_address} to {request.leader_address}"
            )
            leader_address = request.leader_address

        # check if no new entries
        # if so, just return current term
        if len(log) - 1 == request.most_recent_log_idx:
            response = raft_pb2.AppendEntriesResponse(term=current_term, success=True)
            return response
        
        # log all new entries and replicate action
        new_entries = request.entries[request.leader_commit + 1 :]
        for entry in new_entries:
            # add to log and replicate action
            log.append(entry)
            replicate_action(entry, db_path)

        response = raft_pb2.AppendEntriesResponse(term=request.term, success=True)
        return response

    def GetLeader(self, request, context):
        '''
        Returns the leader address.

        Used by clients to determine the leader.
        '''
        global leader_address
        return raft_pb2.GetLeaderResponse(leader_address=leader_address)

# act defines how each server should act
def act():
    '''
    This is where all the action of RAFT takes place.

    This function is called in a loop by the server to check the state of the server and
    do the necessary actions based on the state.

    If follower:
    - Check if the server has received a heartbeat from the leader.
    - If so, become a candidate.
    If candidate:
    - Start a new election round.
    - Send vote requests to all other servers.
    - If majority votes received, become leader.
    If leader:
    - Send heartbeats to all other servers.
    - If majority of servers do not respond, step down as leader.
    '''
    global raft_state, current_term, voted_for, log, leader_address, timer, rec_votes, commit
    current_time = time.time()

    # check to see if we need to change state
    if raft_state == "FOLLOWER":
        # no heartbeat, become candidate
        if current_time >= timer:
            raft_state = "CANDIDATE"
            current_term += 1
            # timer = current_time + random.uniform(3, 5)
            logging.info(
                f"[RAFT] No leader. Becoming candidate for term {current_term}."
            )
    elif raft_state == "CANDIDATE":
        # start new election
        if current_time >= timer:
            rec_votes = 1
            voted_for = idx
            timer = current_time + random.uniform(3, 5)
            logging.info(
                f"[RAFT] Server {idx} election timeout as candidate. Starting new election for term {current_term}."
            )
            for other_servers in all_servers:
                # ask for votes
                try:
                    channel = grpc.insecure_channel(other_servers)
                    stub = raft_pb2_grpc.RaftServiceStub(channel)
                    response = stub.Vote(
                        raft_pb2.VoteRequest(
                            term=current_term,
                            candidate_id=idx,
                            last_log_index=len(log) - 1,
                            last_log_term=log[-1].term if log else 0,
                        )
                    )
                    logging.info(
                        f"[RAFT] Sent vote request to {other_servers} with response: {response}"
                    )
                    if response.vote_granted:
                        rec_votes += 1
                except Exception as e:
                    logging.error(
                        f"[RAFT] Error sending vote request to {other_servers}: {e}"
                    )
            if rec_votes > num_servers // 2:
                # won election
                raft_state = "LEADER"
                leader_address = f"{host}:{port}"
                logging.info(
                    f"[RAFT] Server {idx} (self) elected as leader for term {current_term}."
                )
            else:
                logging.info(
                    f"[RAFT] Server {idx} did not win election for term {current_term}."
                )
    elif raft_state == "LEADER":
        # send out heartbeats to all other servers
        successes = 0
        for other_server in all_servers:
            try:
                channel = grpc.insecure_channel(other_server)
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                # send out all logs
                response = stub.AppendEntries(
                    raft_pb2.AppendEntriesRequest(
                        term=current_term,
                        leader_address=leader_address,
                        most_recent_log_idx=len(log) - 1,
                        term_of_recent_log=log[-1].term if log else 0,
                        entries=log,
                        leader_commit=commit,
                    )
                )
                successes += response.success
                logging.info(
                    f"[RAFT] Sent heartbeat to {other_server} with response: {response}"
                )
                channel.close()
            except Exception as e:
                logging.error(f"[RAFT] Error sending heartbeat to {other_server}: {e}")

        if successes < num_servers // 2:
            # step down, didn't receive enough responses
            logging.info(f"[RAFT] Leader {idx} lost majority. Stepping down.")
            raft_state = "FOLLOWER"
            leader_address = None
        else:
            commit = len(log) - 1
    else:
        logging.error(f"[RAFT] Invalid state: {raft_state}")

    # 0.1 second downtime between each act
    time.sleep(0.1)


def serve():
    """
    Main loop for server. Runs server on separate thread.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    main_pb2_grpc.add_MainServiceServicer_to_server(MainServiceServicer(), server)
    raft_pb2_grpc.add_RaftServiceServicer_to_server(RaftServiceServicer(), server)
    print(f"{host}:{port}")
    server.add_insecure_port(f"{host}:{port}")
    server.start()

    # make sure all servers are running before starting
    for other_server in all_servers:
        while True:
            try:
                channel = grpc.insecure_channel(other_server)
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                response = stub.Vote(
                    raft_pb2.VoteRequest(
                        term=-1, candidate_id=0, last_log_index=0, last_log_term=0
                    )
                )
                logging.info(
                    f"[SETUP] Connected to {other_server} with response: {response}"
                )
                # close channel
                channel.close()
                break
            except Exception as e:
                logging.error(f"[SETUP] Error connecting to {server}: {e}")
                time.sleep(1)

    logging.info(f"[SETUP] Server started on port {port}")
    # wait for random time from 1 to 5 seconds before starting, to allow one server to become leader
    time.sleep(2 * random.random())
    try:
        while True:
            act()
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    serve()
