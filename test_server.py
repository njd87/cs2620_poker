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

"""
Making sure the server is started with the correct arguments.
"""
num_servers = 5
num_lobbies = 2


class TestServer:
    """
    Test server to simulate raft server
    """

    def __init__(self, name, db_path):
        self.leader = None
        self.name = name
        self.db_path = db_path
        self.voted_for = None
        self.servers = None
        self.log = []
        self.online = True

    def Crash(self):
        self.online = False

    def Vote(self, req):
        # vote if not already voted
        if self.voted_for is not None or not self.online:
            return raft_pb2.VoteResponse(term=1, vote_granted=False)
        return raft_pb2.VoteResponse(term=1, vote_granted=True)
    
    def AppendEntries(self, req):
        if not self.online:
            return raft_pb2.AppendEntriesResponse(term=1, success=False)
        # clear voted_for
        self.voted_for = None
        # add new leader
        self.leader = req.leader_address

        # look for new entires
        try:
            new_entries = req.entries[len(self.log) :]
            for entry in new_entries:
                # add to log and replicate action
                self.log.append(entry)
                replicate_action(entry, self.db_path)

        except Exception as e:
            print(f"Error: {e}")

        response = raft_pb2.AppendEntriesResponse(term=req.term, success=True)
        return response

    def GetLeader(self, req):
        return raft_pb2.GetLeaderResponse(leader_address=self.leader)

    def run_for_leader(self):
        """
        Run for leader
        """
        total_servers = len(self.servers)
        votes = 0

        for server in self.servers.values():
            if server != self:
                response = server.Vote(raft_pb2.VoteRequest(term=1))
                if response.vote_granted:
                    votes += 1

        if votes >= total_servers // 2 + 1:
            self.leader = self.name
            return True
        


def handle_requests(req, db_path, all_lobbies=None, username=None):
    client_queue = queue.Queue()
    clients = {}
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
                action=main_pb2.REGISTER, result=True, moolah=500
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
    elif req.action == main_pb2.CONNECT_LOBBY:
        # connect lobby to the main server
        logging.info(f"[MAIN] Lobby {req.username} connected.")
        if (req.username != "") and (req.username not in clients):
            clients[req.username] = client_queue
            connected_to_lobby = True
    elif req.action == main_pb2.SAVE_GAME:
        # save game to data base
        player_name = req.game_history.player
        game_type = req.game_history.game_type
        money_won = req.game_history.money_won

        game_type = (
            "TEXAS HOLD EM" if game_type == main_pb2.TEXAS else "5 CARD"
        )

        # save game to database
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()
        sqlcur.execute(
            "SELECT user_id FROM users WHERE username=?", (player_name,)
        )
        player_id = sqlcur.fetchone()[0]

        # add game to game history
        sqlcur.execute(
            "INSERT INTO game_history (player_id, game_type, money_won) VALUES (?, ?, ?)",
            (player_id, game_type, money_won),
        )

        curr_money = sqlcur.execute(
            "SELECT moolah FROM users WHERE username=?", (player_name,)
        ).fetchone()[0]

        # update moolah in users table
        sqlcur.execute(
            "UPDATE users SET moolah=? WHERE username=?",
            (curr_money + money_won, player_name),
        )
        sqlcur.execute(
            "SELECT moolah FROM users WHERE username=?", (player_name,)
        )

        moolah = sqlcur.fetchone()[0]

        sqlcon.commit()
        sqlcon.close()
        return

    elif req.action == main_pb2.GET_USER_INFO:
        # update user on how much money they have
        username = req.username
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        # check if user exists
        sqlcur.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        )
        if not sqlcur.fetchone():
            client_queue.put(
                main_pb2.MainResponse(
                    action=main_pb2.GET_USER_INFO, result=False
                )
            )
        else:
            sqlcur.execute(
                "SELECT moolah FROM users WHERE username=?", (username,)
            )
            moolah = sqlcur.fetchone()[0]

            client_queue.put(
                main_pb2.MainResponse(
                    action=main_pb2.GET_USER_INFO,
                    result=True,
                    moolah=moolah,
                )
            )

    elif req.action == main_pb2.JOIN_LOBBY:
        # allow user to find available lobbies
        game_type = req.game_type
        # check if lobby is open
        sent_lobby = False
        for idx,_ in enumerate(all_lobbies):
            if (
                (not all_lobbies[idx]["active"])
                and (all_lobbies[idx]["game_type"] == game_type)
                and (all_lobbies[idx]["num_players"] < 4)
            ):
                # tell user it can join lobby
                client_queue.put(
                    main_pb2.MainResponse(
                        action=main_pb2.JOIN_LOBBY,
                        result=True,
                        game_lobby=idx,
                    )
                )
                sent_lobby = True
                break
        if not sent_lobby:
            client_queue.put(
                main_pb2.MainResponse(
                    action=main_pb2.JOIN_LOBBY,
                    result=False,
                )
            )


    elif req.action == main_pb2.VIEW_HISTORY:
        # send history back to client
        curr_username = req.username
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()
        sqlcur.execute(
            "SELECT user_id FROM users WHERE username=?", (curr_username,)
        )
        player_id = sqlcur.fetchone()[0]

        sqlcur.execute(
            "SELECT game_type, money_won FROM game_history WHERE player_id=? ORDER BY game_date DESC",
            (player_id,),
        )

        game_history = sqlcur.fetchall()

        games = []
        for i in range(len(game_history)):
            game = main_pb2.GameHistoryEntry(
                game_type=main_pb2.TEXAS if game_history[i][0] == "TEXAS HOLD EM" else main_pb2.FIVE_HAND,
                money_won=game_history[i][1],
                player=curr_username,
            )
            games.append(game)
        
        client_queue.put(
            main_pb2.MainResponse(
                action=main_pb2.VIEW_HISTORY,
                result=True,
                game_history=games,
            )
        )
        sqlcon.close()
    return client_queue.get()