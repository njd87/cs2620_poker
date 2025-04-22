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
    elif req.action == raft_pb2.SEND_MESSAGE:
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

        except Exception as e:
            message_id = None

        sqlcon.close()
    elif req.action == raft_pb2.PING:
        sender = req.sender
        sent_message = req.sent_message
        message_id = req.message_id

        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        sqlcur.execute(
            "UPDATE messages SET delivered=1 WHERE message_id=?",
            (message_id,),
        )
        sqlcon.commit()

        sqlcon.close()

    elif req.action == raft_pb2.VIEW_UNDELIVERED:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()
        
        username = req.username
        
        sqlcur.execute(
            "UPDATE messages SET delivered=1 WHERE recipient=?",
            (username,),
        )

        sqlcon.commit()
        sqlcon.close()
    elif req.action == raft_pb2.DELETE_MESSAGE:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        message_id = req.message_id
        sqlcur.execute(
            "DELETE FROM messages WHERE message_id=?", (message_id,)
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
                sqlcur.execute(
                    "DELETE FROM messages WHERE sender=? OR recipient=?",
                    (username, username),
                )
                sqlcon.commit()

        sqlcon.close()
    elif req.action == raft_pb2.CONNECT:
        # a new leader was chosen, client connected to new leader
        # add the user to the clients if they are signed in
        if (req.username != ""):
            # update all messages recipient to delivered
            sqlcon = sqlite3.connect(db_path)
            sqlcur = sqlcon.cursor()
            sqlcur.execute(
                "UPDATE messages SET delivered=1 WHERE recipient=?",
                (req.username,),
            )
            sqlcon.commit()
            sqlcon.close()