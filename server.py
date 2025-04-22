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

import chat_pb2_grpc
import chat_pb2
import raft_pb2_grpc
import raft_pb2
import json
import traceback
from replica_helpers import replicate_action

'''
Making sure the server is started with the correct arguments.
'''
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
    for i in range(5)
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


class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    """
    ChatServiceServicer class for ChatServiceServicer

    This class handles the main chat functionality of the server, sending responses via queues.
    All log messages in this service begin with [CHAT].
    """

    def Chat(self, request_iterator, context):
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
                    logging.info(f"[CHAT] Size of request: {sys.getsizeof(req)} bytes")
                    # create a copy of req with different memory
                    log_copy = raft_pb2.LogEntry(
                        action=req.action,
                        username=req.username,
                        passhash=req.passhash,
                        user2=req.user2,
                        sender=req.sender,
                        recipient=req.recipient,
                        message=req.message,
                        sent_message=req.sent_message,
                        n_messages=req.n_messages,
                        message_id=req.message_id,
                        term=current_term,
                    )
                    log.append(log_copy)

                    if req.action == chat_pb2.CHECK_USERNAME:
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
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.CHECK_USERNAME, result=False
                                )
                            )
                        else:
                            client_queue.put(
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.CHECK_USERNAME, result=True
                                )
                            )
                        sqlcon.close()

                    elif req.action == chat_pb2.LOGIN:
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
                                "SELECT COUNT(*) FROM messages WHERE recipient=? AND delivered=0",
                                (req.username,),
                            )

                            n_undelivered = sqlcur.fetchone()[0]

                            response = chat_pb2.ChatResponse(
                                action=chat_pb2.LOGIN,
                                result=True,
                                users=[
                                    s[0]
                                    for s in sqlcur.execute(
                                        "SELECT username FROM users WHERE username != ?",
                                        (req.username,),
                                    ).fetchall()
                                ],
                                n_undelivered=n_undelivered,
                            )

                            client_queue.put(response)

                            # add user to clients
                            username = req.username
                            clients[username] = client_queue
                        else:
                            client_queue.put(
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.LOGIN, result=False
                                )
                            )
                        sqlcon.close()

                    elif req.action == chat_pb2.REGISTER:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        # check to make sure username is not already in use
                        sqlcur.execute(
                            "SELECT * FROM users WHERE username=?", (req.username,)
                        )
                        if sqlcur.fetchone():
                            client_queue.put(
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.REGISTER, result=False
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
                            response = chat_pb2.ChatResponse(
                                action=chat_pb2.REGISTER,
                                result=True,
                                users=[
                                    s[0]
                                    for s in sqlcur.execute(
                                        "SELECT username FROM users WHERE username != ?",
                                        (req.username,),
                                    ).fetchall()
                                ],
                            )

                            client_queue.put(response)

                        sqlcon.close()

                        # add user to clients
                        username = req.username
                        clients[username] = client_queue

                        # send ping_user to all clients
                        for user_q in clients.values():
                            user_q.put(
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.PING_USER, ping_user=username
                                )
                            )

                    elif req.action == chat_pb2.LOAD_CHAT:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        username = req.username
                        user2 = req.user2
                        try:
                            sqlcur.execute(
                                "SELECT sender, recipient, message, message_id FROM messages WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?) ORDER BY time",
                                (username, user2, user2, username),
                            )
                            result = sqlcur.fetchall()
                        except Exception as e:
                            logging.error(f"[CHAT] Error in Load Chat: {e}")
                            result = []

                        formatted_messages = []

                        for sender, recipient, message, message_id in result:
                            formatted_messages.append(
                                chat_pb2.ChatMessage(
                                    sender=sender,
                                    recipient=recipient,
                                    message=message,
                                    message_id=message_id,
                                )
                            )

                        client_queue.put(
                            chat_pb2.ChatResponse(
                                action=chat_pb2.LOAD_CHAT, messages=formatted_messages
                            )
                        )
                        sqlcon.close()

                    elif req.action == chat_pb2.SEND_MESSAGE:
                        sender = req.sender
                        recipient = req.recipient
                        message = req.message
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        try:
                            sqlcur.execute(
                                "INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)",
                                (sender, recipient, message),
                            )
                            sqlcon.commit()

                            # get the message_id
                            sqlcur.execute(
                                "SELECT message_id FROM messages WHERE sender=? AND recipient=? AND message=? ORDER BY time DESC LIMIT 1",
                                (sender, recipient, message),
                            )
                            message_id = sqlcur.fetchone()[0]

                            # send message to recipient
                            client_queue.put(
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.SEND_MESSAGE, message_id=message_id
                                )
                            )

                            # ping recipient if online
                            if recipient in clients:
                                clients[recipient].put(
                                    chat_pb2.ChatResponse(
                                        action=chat_pb2.PING,
                                        sender=sender,
                                        sent_message=message,
                                        message_id=message_id,
                                    )
                                )

                        except Exception as e:
                            logging.error(f"[CHAT] Error sending message: {e}")
                            message_id = None

                        sqlcon.close()

                    elif req.action == chat_pb2.PING:
                        # update message to delivered
                        action = req.action
                        sender = req.sender
                        sent_message = req.sent_message
                        message_id = req.message_id

                        client_queue.put(
                            chat_pb2.ChatResponse(
                                action=action,
                                sender=sender,
                                sent_message=sent_message,
                                message_id=message_id,
                            )
                        )

                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        logging.info(
                            f"[CHAT] Updating message {message_id} to delivered."
                        )

                        sqlcur.execute(
                            "UPDATE messages SET delivered=1 WHERE message_id=?",
                            (message_id,),
                        )
                        sqlcon.commit()

                        sqlcon.close()

                    elif req.action == chat_pb2.VIEW_UNDELIVERED:
                        # view undelivered messages
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        username = req.username
                        n_messages = req.n_messages

                        sqlcur.execute(
                            "SELECT sender, recipient, message, message_id FROM messages WHERE recipient=? AND delivered=0 ORDER BY time DESC LIMIT ?",
                            (username, n_messages),
                        )
                        result = sqlcur.fetchall()

                        # format messages to ChatMessage
                        messages_formatted = []

                        for sender, recipient, message, message_id in result:
                            messages_formatted.append(
                                chat_pb2.ChatMessage(
                                    sender=sender,
                                    recipient=recipient,
                                    message=message,
                                    message_id=message_id,
                                )
                            )

                        client_queue.put(
                            chat_pb2.ChatResponse(
                                action=chat_pb2.VIEW_UNDELIVERED,
                                messages=messages_formatted,
                            )
                        )

                        sqlcur.execute(
                            "UPDATE messages SET delivered=1 WHERE recipient=?",
                            (username,),
                        )

                        sqlcon.commit()
                        sqlcon.close()

                    elif req.action == chat_pb2.DELETE_MESSAGE:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        message_id = req.message_id
                        sqlcur.execute(
                            "DELETE FROM messages WHERE message_id=?", (message_id,)
                        )
                        sqlcon.commit()

                        sqlcon.close()
                        client_queue.put(
                            chat_pb2.ChatResponse(
                                action=chat_pb2.DELETE_MESSAGE, message_id=message_id
                            )
                        )

                        # if recipient is online, ping recipient to update chat
                        if req.recipient in clients:
                            clients[req.recipient].put(
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.PING,
                                    sender=req.sender,
                                    sent_message=req.message,
                                    message_id=message_id,
                                )
                            )

                    elif req.action == chat_pb2.DELETE_ACCOUNT:
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
                                sqlcur.execute(
                                    "DELETE FROM messages WHERE sender=? OR recipient=?",
                                    (username, username),
                                )
                                sqlcon.commit()

                                client_queue.put(
                                    chat_pb2.ChatResponse(
                                        action=chat_pb2.DELETE_ACCOUNT, result=True
                                    )
                                )
                                # tell server to ping users to update their chat, remove from connected users

                                # delete user from clients
                                if username in clients:
                                    del clients[username]

                                for user_q in clients.values():
                                    user_q.put(
                                        chat_pb2.ChatResponse(
                                            action=chat_pb2.PING_USER,
                                            ping_user=username,
                                        )
                                    )

                            # username exists but passhash is wrong
                            else:
                                client_queue.put(
                                    chat_pb2.ChatResponse(
                                        action=chat_pb2.DELETE_ACCOUNT, result=False
                                    )
                                )
                        else:
                            # username doesn't exist
                            client_queue.put(
                                chat_pb2.ChatResponse(
                                    action=chat_pb2.DELETE_ACCOUNT, result=False
                                )
                            )

                        sqlcon.close()

                    elif req.action == chat_pb2.PING_USER:
                        # ping that a user has been added or deleted
                        action = req.action
                        ping_user = req.ping_user
                        client_queue.put(
                            chat_pb2.ChatResponse(action=action, ping_user=ping_user)
                        )
                    elif req.action == chat_pb2.CONNECT:
                        # a new leader was chosen, client connected to new leader
                        # add the user to the clients if they are signed in
                        logging.info(f"[CHAT] {req.username} connected.")
                        if (req.username != "") and (req.username not in clients):
                            clients[req.username] = client_queue
                            # update all messages recipient to delivered
                            sqlcon = sqlite3.connect(db_path)
                            sqlcur = sqlcon.cursor()
                            sqlcur.execute(
                                "UPDATE messages SET delivered=1 WHERE recipient=?",
                                (req.username,),
                            )
                            sqlcon.commit()
                            sqlcon.close()
                    else:
                        logging.error(f"[CHAT] Invalid action: {req.action}")
            except Exception as e:
                tb = traceback.extract_tb(e.__traceback__)
                line_number = tb[-1].lineno if tb else "unknown"
                logging.error(
                    f"[CHAT] Error handling requests at line {line_number}: {traceback.format_exc()}"
                )
            finally:
                if username in clients:
                    del clients[username]
                    logging.info(f"[CHAT] {username} disconnected.")

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
        global current_term, voted_for

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
            leader_address = None
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
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServiceServicer(), server)
    raft_pb2_grpc.add_RaftServiceServicer_to_server(RaftServiceServicer(), server)
    print(f"{host}:{port}")
    server.add_insecure_port(f"0.0.0.0:{port}")
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
