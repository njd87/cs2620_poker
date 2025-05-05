from concurrent import futures
import unittest
import os
import sqlite3

import grpc
import main_pb2_grpc
import main_pb2
import raft_pb2_grpc
import raft_pb2
import random

from setup import reset_database, structure_tables
from test_server import handle_requests, TestServer
from test_lobby import Deck, TestTexasHoldem

unittest.TestLoader.sortTestMethodsUsing = None


class TestDatabaseSetup(unittest.TestCase):
    """
    Tests "setup.py" file for resetting and structuring the database.

    Tests the following functions:
    - reset_database
    - structure_tables
    """

    def test_reset_database(self):
        reset_database(
            [
                "data/r1/test_poker.db",
                "data/r2/test_poker.db",
                "data/r3/test_poker.db",
                "data/r4/test_poker.db",
                "data/r5/test_poker.db",
            ]
        )

        self.assertFalse(os.path.exists("data/r1/test_poker.db"))
        self.assertFalse(os.path.exists("data/r2/test_poker.db"))
        self.assertFalse(os.path.exists("data/r3/test_poker.db"))
        self.assertFalse(os.path.exists("data/r4/test_poker.db"))
        self.assertFalse(os.path.exists("data/r5/test_poker.db"))

    def test_structure_tables(self):
        # check if the tables are created correctly
        structure_tables("data/r1/test_poker.db")
        conn = sqlite3.connect("data/r1/test_poker.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game_history';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r2/test_poker.db")
        conn = sqlite3.connect("data/r2/test_poker.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game_history';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r3/test_poker.db")
        conn = sqlite3.connect("data/r3/test_poker.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game_history';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r4/test_poker.db")
        conn = sqlite3.connect("data/r4/test_poker.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game_history';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r5/test_poker.db")
        conn = sqlite3.connect("data/r5/test_poker.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game_history';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()


class TestServerProcessResponse(unittest.TestCase):
    """
    Test cases for communicating between the server and client via JSON encoding and decoding.
    """

    @classmethod
    def setUpClass(cls):
        # Code to run once at the beginning of the test class
        # check to see if data/test_poker.db exists
        # if it does, delete it
        if os.path.exists("data/r1/test_poker.db"):
            os.remove("data/r1/test_poker.db")
            print("Deleted test_poker.db")
        if os.path.exists("data/r2/test_poker.db"):
            os.remove("data/r2/test_poker.db")
            print("Deleted test_poker.db")
        if os.path.exists("data/r3/test_poker.db"):
            os.remove("data/r3/test_poker.db")
            print("Deleted test_poker.db")
        if os.path.exists("data/r4/test_poker.db"):
            os.remove("data/r4/test_poker.db")
            print("Deleted test_poker.db")
        if os.path.exists("data/r5/test_poker.db"):
            os.remove("data/r5/test_poker.db")
            print("Deleted test_poker.db")

        # create the database
        structure_tables("data/r1/test_poker.db")
        structure_tables("data/r2/test_poker.db")
        structure_tables("data/r3/test_poker.db")
        structure_tables("data/r4/test_poker.db")
        structure_tables("data/r5/test_poker.db")

        cls.server1 = TestServer("s1", "data/r1/test_poker.db")
        cls.server2 = TestServer("s2", "data/r2/test_poker.db")
        cls.server3 = TestServer("s3", "data/r3/test_poker.db")
        cls.server4 = TestServer("s4", "data/r4/test_poker.db")
        cls.server5 = TestServer("s5", "data/r5/test_poker.db")

        cls.all_servers = {
            "s1": cls.server1,
            "s2": cls.server2,
            "s3": cls.server3,
            "s4": cls.server4,
            "s5": cls.server5,
        }

        cls.server1.servers = cls.all_servers
        cls.server2.servers = cls.all_servers
        cls.server3.servers = cls.all_servers
        cls.server4.servers = cls.all_servers
        cls.server5.servers = cls.all_servers

    def test1a_elect_leader(self):
        # elect server 1 as leader
        self.server1.run_for_leader()

        # construct AppendEntriesRequest
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

        # check getleader
        for server in self.all_servers:
            response = self.all_servers[server].GetLeader(raft_pb2.GetLeaderRequest())
            self.assertEqual(response.leader_address, "s1")

    def test1b_register_user(self):
        # register user, check if it exists in the database
        request = main_pb2.MainRequest(
            action=main_pb2.REGISTER, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )
        self.server1.log.append(log_copy)
        # act as leader
        response = handle_requests(request, self.server1.db_path)
        self.assertEqual(response.result, True)

        # send AppendEntriesRequest to all servers
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

        # ensure all servers have the same database
        for server in self.all_servers:
            conn = sqlite3.connect(self.all_servers[server].db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username='foo';")
            user = cursor.fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user[1], "foo")
            cursor.execute("SELECT COUNT(*) FROM users;")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)
            conn.close()

    def test1c_register_user_exists(self):
        # if user already exists, it should return False
        request = main_pb2.MainRequest(
            action=main_pb2.REGISTER, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )

        # act as leader
        response = handle_requests(request, self.server1.db_path)
        self.assertEqual(response.result, False)

        self.server1.log.append(log_copy)

        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

        for server in self.all_servers:
            conn = sqlite3.connect(self.all_servers[server].db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username='foo';")
            user = cursor.fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user[1], "foo")
            cursor.execute("SELECT COUNT(*) FROM users;")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)
            conn.close()

    def test1d_login_user(self):
        # login existing user, check return true
        request = main_pb2.MainRequest(
            action=main_pb2.LOGIN, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )

        response = handle_requests(request, self.server1.db_path)
        self.assertEqual(response.result, True)
        self.server1.log.append(log_copy)

        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

    def test1e_login_user_invalid(self):
        # login with invalid password, should return False
        request = main_pb2.MainRequest(
            action=main_pb2.LOGIN, username="foo", passhash="baz"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )

        response = handle_requests(request, self.server1.db_path)
        self.assertEqual(response.result, False)
        self.server1.log.append(log_copy)

        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

    def test1f_register_other(self):
        # register another user, check if it exists in the database
        request = main_pb2.MainRequest(
            action=main_pb2.REGISTER, username="bar", passhash="baz"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, True)

        self.server1.log.append(log_copy)
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

    def test_2a_get_user_info(self):
        # get user info, check if it exists in the database
        request = main_pb2.MainRequest(
            action=main_pb2.GET_USER_INFO, username="notauser"
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, False)
    
    def test_2b_get_user_info(self):
        # get user info, check if it exists in the database
        request = main_pb2.MainRequest(
            action = main_pb2.GET_USER_INFO, username="bar"
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, True)
        self.assertEqual(response.moolah, 500)
    
    def test_2c_get_user_info(self):
        # get user info, check if it exists in the database
        request = main_pb2.MainRequest(
            action = main_pb2.GET_USER_INFO, username="foo"
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, True)
        self.assertEqual(response.moolah, 500)

    def test_3a_join_lobby(self):
        # try to join a lobby, should return False, none available
        request = main_pb2.MainRequest(
            action = main_pb2.JOIN_LOBBY, game_type=0
        )
        response = handle_requests(request, db_path=self.server1.db_path,
                                   all_lobbies = [])
        self.assertEqual(response.result, False)

    def test_3b_join_lobby(self):
        # try to join a lobby, should return True
        request = main_pb2.MainRequest(
            action = main_pb2.JOIN_LOBBY, game_type=0
        )
        response = handle_requests(request, db_path=self.server1.db_path,
                                   all_lobbies = [{"active": True, "game_type": 0, "num_players": 0},
                                                  {"active": False, "game_type": 0, "num_players": 0}])
        self.assertEqual(response.result, True)
        self.assertEqual(response.game_lobby, 1)

    def test_3c_join_lobby(self):
        # try to join a lobby, should return False, none active
        request = main_pb2.MainRequest(
            action = main_pb2.JOIN_LOBBY, game_type=0
        )
        response = handle_requests(request, db_path=self.server1.db_path,
                                   all_lobbies = [{"active": True, "game_type": 0, "num_players": 0},
                                                  {"active": True, "game_type": 0, "num_players": 0}])
        self.assertEqual(response.result, False)

    def test_3d_join_lobby(self):
        # try to join a lobby, should return False, none available of correct mode
        request = main_pb2.MainRequest(
            action = main_pb2.JOIN_LOBBY, game_type=0
        )
        response = handle_requests(request, db_path=self.server1.db_path,
                                   all_lobbies = [{"active": True, "game_type": 0, "num_players": 0},
                                                  {"active": False, "game_type": 1, "num_players": 0}])
        self.assertEqual(response.result, False)

    def test_3e_join_lobby(self):
        # try to join a lobby, should return False, none available with enough space
        request = main_pb2.MainRequest(
            action = main_pb2.JOIN_LOBBY, game_type=0
        )
        response = handle_requests(request, db_path=self.server1.db_path,
                                   all_lobbies = [{"active": True, "game_type": 0, "num_players": 0},
                                                  {"active": False, "game_type": 0, "num_players": 4}])
        self.assertEqual(response.result, False)

    def test_3f_join_lobby(self):
        # try to join a lobby, should return True, just enough space
        request = main_pb2.MainRequest(
            action = main_pb2.JOIN_LOBBY, game_type=0
        )
        response = handle_requests(request, db_path=self.server1.db_path,
                                   all_lobbies = [{"active": True, "game_type": 0, "num_players": 0},
                                                  {"active": False, "game_type": 0, "num_players": 3}])
        self.assertEqual(response.result, True)
        self.assertEqual(response.game_lobby, 1)

    def test_4a_save_game(self):
        # try to save game, won money
        request = main_pb2.MainRequest(
            action=main_pb2.SAVE_GAME,
            game_history=main_pb2.GameHistoryEntry(
                game_type=1, money_won=100, player="bar"
            ),
        )
        _ = handle_requests(request, db_path=self.server1.db_path)
        request1 = main_pb2.MainRequest(
            action=main_pb2.GET_USER_INFO, username="bar"
        )  
        response1 = handle_requests(request1, db_path=self.server1.db_path)
        self.assertEqual(response1.moolah, 600)

    def test_4b_save_game(self):
        # try to save game, lost money
        request = main_pb2.MainRequest(
            action=main_pb2.SAVE_GAME,
            game_history=main_pb2.GameHistoryEntry(
                game_type=2, money_won=-100, player="bar"
            ),
        )
        _ = handle_requests(request, db_path=self.server1.db_path)
        request1 = main_pb2.MainRequest(
            action=main_pb2.GET_USER_INFO, username="bar"
        )  
        response1 = handle_requests(request1, db_path=self.server1.db_path)
        self.assertEqual(response1.moolah, 500)

    def test_4c_view_history(self):
        request = main_pb2.MainRequest(
            action=main_pb2.VIEW_HISTORY, username="bar"
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, True)
        self.assertEqual(len(response.game_history), 2)
        self.assertEqual(response.game_history[0].game_type, 1)
        self.assertEqual(response.game_history[0].money_won, 100)
        self.assertEqual(response.game_history[0].player, "bar")
        self.assertEqual(response.game_history[1].game_type, 2)
        self.assertEqual(response.game_history[1].money_won, -100)
        self.assertEqual(response.game_history[1].player, "bar")

    def test_5b_delete_account_invalid_pass(self):
        # delete account with invalid password, should return False
        request = main_pb2.MainRequest(
            action=main_pb2.DELETE_ACCOUNT, username="foo", passhash="baz"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)

        self.assertEqual(response.result, False)

        self.server1.log.append(log_copy)

        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response1 = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response1.success, True)

        for server in self.all_servers:
            conn = sqlite3.connect(self.all_servers[server].db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE username='foo';")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)

            cursor.execute(
                "SELECT COUNT(*) FROM game_history WHERE player_id=1;"
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()

    def test_5c_delete_account_invalid_user(self):
        # delete account with invalid username, should return False
        request = main_pb2.MainRequest(
            action=main_pb2.DELETE_ACCOUNT, username="baz", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, False)

        self.server1.log.append(log_copy)

        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response1 = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response1.success, True)

        for server in self.all_servers:
            conn = sqlite3.connect(self.all_servers[server].db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE username='baz';")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()

    def test_5d_delete_account(self):
        # delete account, check if it is removed from the database
        request = main_pb2.MainRequest(
            action=main_pb2.DELETE_ACCOUNT, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            money_to_add=request.money_to_add,
            game_history=raft_pb2.GameHistoryEntry(
                game_type=request.game_history.game_type,
                money_won=request.game_history.money_won,
                player=request.game_history.player,
            ),
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, True)

        self.server1.log.append(log_copy)

        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response1 = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response1.success, True)

        for server in self.all_servers:
            conn = sqlite3.connect(self.all_servers[server].db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE username='foo';")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)

            cursor.execute(
                "SELECT COUNT(*) FROM game_history WHERE player_id=1;"
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()


class TestServerCrashes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server1 = TestServer("s1", "data/r1/test_poker.db")
        cls.server2 = TestServer("s2", "data/r2/test_poker.db")
        cls.server3 = TestServer("s3", "data/r3/test_poker.db")
        cls.server4 = TestServer("s4", "data/r4/test_poker.db")
        cls.server5 = TestServer("s5", "data/r5/test_poker.db")

        cls.all_servers = {
            "s1": cls.server1,
            "s2": cls.server2,
            "s3": cls.server3,
            "s4": cls.server4,
            "s5": cls.server5,
        }

        cls.server1.servers = cls.all_servers
        cls.server2.servers = cls.all_servers
        cls.server3.servers = cls.all_servers
        cls.server4.servers = cls.all_servers
        cls.server5.servers = cls.all_servers

    def test1a_elect_leader(self):
        # elect server 1 as leader
        self.server1.run_for_leader()

        # construct AppendEntriesRequest
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

        # check getleader
        for server in self.all_servers:
            response = self.all_servers[server].GetLeader(raft_pb2.GetLeaderRequest())
            self.assertEqual(response.leader_address, "s1")

    def test1b_elect_leader_once_crash(self):
        # elect server 1 as leader
        self.server1.Crash()
        self.server2.run_for_leader()

        # construct AppendEntriesRequest
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s2", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s2":
                response = self.all_servers[server].AppendEntries(request)

        # check getleader
        for server in self.all_servers:
            response = self.all_servers[server].GetLeader(raft_pb2.GetLeaderRequest())
            self.assertIn(response.leader_address, ["s1", "s2", "s3"])

    def test1b_elect_leader_twice_crash(self):
        # elect server 1 as leader
        self.server2.Crash()
        self.server3.run_for_leader()

        # construct AppendEntriesRequest
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s3", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s3":
                response = self.all_servers[server].AppendEntries(request)

        # check getleader
        for server in self.all_servers:
            response = self.all_servers[server].GetLeader(raft_pb2.GetLeaderRequest())
            self.assertIn(response.leader_address, ["s1", "s2", "s3"])

    def test1b_elect_leader_thrice_crash(self):
        # elect server 1 as leader
        self.server3.Crash()
        self.server4.run_for_leader()

        # server4 should fail election
        self.assertEqual(self.server4.leader, "s2")

class TestDeck(unittest.TestCase):
    def setUp(self):
        self.deck = Deck()

    def test_deck_initialization(self):
        self.assertEqual(len(self.deck.cards), 52)
        self.assertEqual(len(set(self.deck.cards)), 52)  # All cards should be unique

    def test_deck_shuffle(self):
        original_order = self.deck.cards.copy()
        self.deck.shuffle()
        self.assertNotEqual(original_order, self.deck.cards)

    def test_deck_reshuffle(self):
        original_order = self.deck.cards.copy()
        self.deck.reshuffle()
        self.assertNotEqual(original_order, self.deck.cards)
        self.assertEqual(len(self.deck.cards), 52)
        self.assertEqual(len(set(self.deck.cards)), 52)
    
    def test_deck_deal(self):
        original_length = len(self.deck.cards)
        dealt_cards = self.deck.deal(5)
        self.assertEqual(len(dealt_cards), 5)
        self.assertEqual(len(self.deck.cards), original_length - 5)
        for card in dealt_cards:
            self.assertNotIn(card, self.deck.cards)

class TestEvaluateHand(unittest.TestCase):
    def setUp(self):
        self.g = TestTexasHoldem()

    def assertBest(self, cards7, best5):
        """Helper: evaluate_hand(cards7) == evaluate_5cards(best5)."""
        got = self.g.evaluate_hand(cards7)
        want = self.g.evaluate_5cards(best5)
        self.assertEqual(got, want,
                         f"\n7 cards: {cards7}\nexpected best: {best5}\ngot strength: {got}")

    def test_high_card(self):
        cards = ['2♠','4♣','6♦','8♥','T♠','J♣','K♦']
        # highest five: 6,8,T,J,K
        best = ['6♦','8♥','T♠','J♣','K♦']
        self.assertBest(cards, best)

    def test_one_pair(self):
        cards = ['A♠','A♥','2♦','5♣','9♦','K♣','3♥']
        # pair of Aces + K,9,5
        best = ['A♠','A♥','K♣','9♦','5♣']
        self.assertBest(cards, best)

    def test_two_pair(self):
        cards = ['K♠','K♦','Q♣','Q♥','2♦','3♣','J♥']
        # KKQQJ
        best = ['K♠','K♦','Q♣','Q♥','J♥']
        self.assertBest(cards, best)

    def test_three_of_a_kind(self):
        cards = ['5♠','5♦','5♣','2♥','9♣','K♦','T♥']
        # 555K T
        best = ['5♠','5♦','5♣','K♦','T♥']
        self.assertBest(cards, best)

    def test_straight(self):
        cards = ['9♠','7♦','8♣','6♥','5♠','2♦','K♥']
        # straight 5-9
        best = ['5♠','6♥','7♦','8♣','9♠']
        self.assertBest(cards, best)

    def test_wheel_straight(self):
        cards = ['A♠','2♦','3♣','4♥','5♣','J♦','K♥']
        # wheel A-5
        best = ['A♠','2♦','3♣','4♥','5♣']
        self.assertBest(cards, best)

    def test_flush(self):
        cards = ['2♦','4♦','6♦','8♦','T♦','A♣','K♠']
        # 5-card diamond flush
        best = ['2♦','4♦','6♦','8♦','T♦']
        self.assertBest(cards, best)

    def test_full_house(self):
        cards = ['3♠','3♦','3♣','2♥','2♣','9♦','K♥']
        # 33322
        best = ['3♠','3♦','3♣','2♥','2♣']
        self.assertBest(cards, best)

    def test_four_of_a_kind(self):
        cards = ['7♠','7♥','7♦','7♣','2♠','A♦','4♥']
        # 7777A
        best = ['7♠','7♥','7♦','7♣','A♦']
        self.assertBest(cards, best)

    def test_straight_flush(self):
        cards = ['5♥','6♥','7♥','8♥','9♥','K♠','A♦']
        # hearts 5-9
        best = ['5♥','6♥','7♥','8♥','9♥']
        self.assertBest(cards, best)

    def test_prefer_higher_straight(self):
        cards = ['3♣','4♦','5♠','6♥','7♣','8♦','9♥']
        # two straights: 3-7 and 5-9 → pick 5-9
        best = ['5♠','6♥','7♣','8♦','9♥']
        self.assertBest(cards, best)
