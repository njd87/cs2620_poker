from concurrent import futures
import unittest
import os
import sqlite3

import grpc
import chat_pb2_grpc
import chat_pb2
import raft_pb2_grpc
import raft_pb2
from setup import reset_database, structure_tables
from test_server import handle_requests, TestServer

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
                "data/r1/test_messenger.db",
                "data/r2/test_messenger.db",
                "data/r3/test_messenger.db",
                "data/r4/test_messenger.db",
                "data/r5/test_messenger.db",
            ]
        )

        self.assertFalse(os.path.exists("data/r1/test_messenger.db"))
        self.assertFalse(os.path.exists("data/r2/test_messenger.db"))
        self.assertFalse(os.path.exists("data/r3/test_messenger.db"))
        self.assertFalse(os.path.exists("data/r4/test_messenger.db"))
        self.assertFalse(os.path.exists("data/r5/test_messenger.db"))

    def test_structure_tables(self):
        # check if the tables are created correctly
        structure_tables("data/r1/test_messenger.db")
        conn = sqlite3.connect("data/r1/test_messenger.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r2/test_messenger.db")
        conn = sqlite3.connect("data/r2/test_messenger.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r3/test_messenger.db")
        conn = sqlite3.connect("data/r3/test_messenger.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r4/test_messenger.db")
        conn = sqlite3.connect("data/r4/test_messenger.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages';"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

        structure_tables("data/r5/test_messenger.db")
        conn = sqlite3.connect("data/r5/test_messenger.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users';"
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages';"
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
        # check to see if data/test_messenger.db exists
        # if it does, delete it
        if os.path.exists("data/r1/test_messenger.db"):
            os.remove("data/r1/test_messenger.db")
            print("Deleted test_messenger.db")
        if os.path.exists("data/r2/test_messenger.db"):
            os.remove("data/r2/test_messenger.db")
            print("Deleted test_messenger.db")
        if os.path.exists("data/r3/test_messenger.db"):
            os.remove("data/r3/test_messenger.db")
            print("Deleted test_messenger.db")
        if os.path.exists("data/r4/test_messenger.db"):
            os.remove("data/r4/test_messenger.db")
            print("Deleted test_messenger.db")
        if os.path.exists("data/r5/test_messenger.db"):
            os.remove("data/r5/test_messenger.db")
            print("Deleted test_messenger.db")

        # create the database
        structure_tables("data/r1/test_messenger.db")
        structure_tables("data/r2/test_messenger.db")
        structure_tables("data/r3/test_messenger.db")
        structure_tables("data/r4/test_messenger.db")
        structure_tables("data/r5/test_messenger.db")

        cls.server1 = TestServer("s1", "data/r1/test_messenger.db")
        cls.server2 = TestServer("s2", "data/r2/test_messenger.db")
        cls.server3 = TestServer("s3", "data/r3/test_messenger.db")
        cls.server4 = TestServer("s4", "data/r4/test_messenger.db")
        cls.server5 = TestServer("s5", "data/r5/test_messenger.db")

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
        request = chat_pb2.ChatRequest(
            action=chat_pb2.REGISTER, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        self.server1.log.append(log_copy)
        # act as leader
        response = handle_requests(request, self.server1.db_path)
        self.assertEqual(response.result, True)
        self.assertEqual(response.users, [])

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
        request = chat_pb2.ChatRequest(
            action=chat_pb2.REGISTER, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
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
        request = chat_pb2.ChatRequest(
            action=chat_pb2.LOGIN, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
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
        request = chat_pb2.ChatRequest(
            action=chat_pb2.LOGIN, username="foo", passhash="baz"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
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
        request = chat_pb2.ChatRequest(
            action=chat_pb2.REGISTER, username="bar", passhash="baz"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.result, True)
        self.assertEqual(response.users, ["foo"])

        self.server1.log.append(log_copy)
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response.success, True)

    def test2a_send_message(self):
        # send message between two users, check if it exists in the database
        request = chat_pb2.ChatRequest(
            action=chat_pb2.SEND_MESSAGE,
            sender="foo",
            recipient="bar",
            message="Hello, World!",
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertIsNotNone(response.message_id)

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
            cursor.execute(
                "SELECT * FROM messages WHERE message_id=?;", (response.message_id,)
            )
            message = cursor.fetchone()
            self.assertIsNotNone(message)
            self.assertEqual(message[1], "foo")
            self.assertEqual(message[2], "bar")
            self.assertEqual(message[3], "Hello, World!")
            conn.close()

    def test2b_send_many_msgs(self):
        # send many messages between two users, check if they exist in the database
        for i in range(1000):
            request = chat_pb2.ChatRequest(
                action=chat_pb2.SEND_MESSAGE,
                sender="foo",
                recipient="bar",
                message=f"Message {i}",
            )
            log_copy = raft_pb2.LogEntry(
                action=request.action,
                username=request.username,
                passhash=request.passhash,
                user2=request.user2,
                sender=request.sender,
                recipient=request.recipient,
                message=request.message,
                sent_message=request.sent_message,
                n_messages=request.n_messages,
                message_id=request.message_id,
                term=1,
            )
            response = handle_requests(request, db_path=self.server1.db_path)

            self.assertIsNotNone(response.message_id)

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
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE sender='foo' AND recipient='bar';"
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1001)
            conn.close()

    def test3a_ping(self):
        # ping user, check if message is delivered
        request = chat_pb2.ChatRequest(
            action=chat_pb2.PING,
            sender="foo",
            sent_message="Hello, World!",
            message_id=1,
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)

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
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE sender='foo' AND delivered=1;"
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)
            conn.close()

    def test3b_load_chat(self):
        # load chat between two users, check if messages are returned
        request = chat_pb2.ChatRequest(
            action=chat_pb2.LOAD_CHAT, username="foo", user2="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        # check to make sure response.messages is not empty
        self.assertNotEqual(response.messages, [])

        self.server1.log.append(log_copy)
        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response1 = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response1.success, True)

    def test3c_load_chat_empty(self):
        # check to make sure empty chat returns no messages
        request = chat_pb2.ChatRequest(
            action=chat_pb2.LOAD_CHAT, username="foo", user2="baz"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        response = handle_requests(request, db_path=self.server1.db_path)
        self.assertEqual(response.messages, [])

        self.server1.log.append(log_copy)

        request = raft_pb2.AppendEntriesRequest(
            term=1, leader_address="s1", entries=self.server1.log
        )

        for server in self.all_servers:
            if server != "s1":
                response1 = self.all_servers[server].AppendEntries(request)
                self.assertEqual(response1.success, True)

    def test4a_view_undelivered(self):
        # view undelivered messages, check if they are returned
        request = chat_pb2.ChatRequest(
            action=chat_pb2.VIEW_UNDELIVERED, username="bar", n_messages=10
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        _ = handle_requests(request, db_path=self.server1.db_path)

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
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE recipient='bar' AND delivered=0;"
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()

    def test5a_delete_message(self):
        # delete message, check if it is removed from the database
        request = chat_pb2.ChatRequest(action=chat_pb2.DELETE_MESSAGE, message_id=1)
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
            term=1,
        )
        _ = handle_requests(request, db_path=self.server1.db_path)

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
            cursor.execute("SELECT COUNT(*) FROM messages WHERE message_id=1;")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()

    def test5b_delete_account_invalid_pass(self):
        # delete account with invalid password, should return False
        request = chat_pb2.ChatRequest(
            action=chat_pb2.DELETE_ACCOUNT, username="foo", passhash="baz"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
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
                "SELECT COUNT(*) FROM messages WHERE sender='foo' OR recipient='foo';"
            )
            count = cursor.fetchone()[0]
            self.assertNotEqual(count, 0)
            conn.close()

    def test5c_delete_account_invalid_user(self):
        # delete account with invalid username, should return False
        request = chat_pb2.ChatRequest(
            action=chat_pb2.DELETE_ACCOUNT, username="baz", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
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

    def test5d_delete_account(self):
        # delete account, check if it is removed from the database
        request = chat_pb2.ChatRequest(
            action=chat_pb2.DELETE_ACCOUNT, username="foo", passhash="bar"
        )
        log_copy = raft_pb2.LogEntry(
            action=request.action,
            username=request.username,
            passhash=request.passhash,
            user2=request.user2,
            sender=request.sender,
            recipient=request.recipient,
            message=request.message,
            sent_message=request.sent_message,
            n_messages=request.n_messages,
            message_id=request.message_id,
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
                "SELECT COUNT(*) FROM messages WHERE sender='foo' OR recipient='foo';"
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()


class TestServerCrashes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server1 = TestServer("s1", "data/r1/test_messenger.db")
        cls.server2 = TestServer("s2", "data/r2/test_messenger.db")
        cls.server3 = TestServer("s3", "data/r3/test_messenger.db")
        cls.server4 = TestServer("s4", "data/r4/test_messenger.db")
        cls.server5 = TestServer("s5", "data/r5/test_messenger.db")

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
            self.assertEqual(response.leader_address, "s2")

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
            self.assertEqual(response.leader_address, "s3")

    def test1b_elect_leader_thrice_crash(self):
        # elect server 1 as leader
        self.server3.Crash()
        self.server4.run_for_leader()

        # server4 should fail election
        self.assertEqual(self.server4.leader, "s3")


# '''
# Manual UI unit tests:

# - Correctly register a user
# - Correctly login a user
# - Correctly fails login with incorrect password
# - Correctly fails register with existing user
# - Correctly fails to submit empty message/usernames
# - Correctly reads undelivered messages
# - Correctly selects number of undelivered messages
# - Correctly sends messages live
# - Correctly sends pings
# - Correctly deletes own messages
# - Correctly fails to delete other users' messages
# - Correctly deletes own account
# - Correctly fails to delete other users' accounts
# - Correctly pings users' "users" tab when user deletes
# - Correctly pings users' "users" tab when user registers
# - Correctly loads chat history for existing chat
# - Correctly loads chat history for non-existing chat
# - Correctly fails to delete account with incorrect password

# '''
