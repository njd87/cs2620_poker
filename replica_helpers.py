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

        sqlcon.close()
    elif req.action == raft_pb2.SAVE_GAME:
        player_name = req.game_history.player
        game_type = req.game_history.game_type
        money_won = req.game_history.money_won

        game_type = "TEXAS HOLD EM" if game_type == raft_pb2.TEXAS else "5 CARD"

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