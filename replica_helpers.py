import raft_pb2_grpc
import raft_pb2
import sqlite3
import os
import hashlib
import grpc

def replicate_action(req, db_path):
    """
    Replicate the action to the database

    Parameters:
    - req:
        the request to replicate
    - db_path:
        the path to the database
    """
    if req.action == raft_pb2.REGISTER:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        # check to make sure username is not already in use
        sqlcur.execute(
            "SELECT * FROM users WHERE username=?", (req.username,)
        )
        if sqlcur.fetchone():
            pass
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
        sqlcon.close()
    elif req.action == raft_pb2.DELETE_ACCOUNT:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        username = req.username
        passhash = req.passhash

        # check if user exists
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

        sqlcon.close()
    elif req.action == raft_pb2.CONNECT:
        # a new leader was chosen, client connected to new leader
        # add the user to the clients if they are signed in
        pass