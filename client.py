import os
import queue
import sys
import threading
import time
import tkinter as tk
import json
import logging

import grpc
import numpy as np

import main_pb2_grpc
import main_pb2
import raft_pb2_grpc
import raft_pb2
import lobby_pb2_grpc
import lobby_pb2

num_servers = 2

# log to a file
log_file = "logs/client.log"

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# if the file does not exist in the current directory, create it
if not os.path.exists(log_file):
    with open(log_file, "w") as f:
        pass

# open config/config.json
with open("config/config.json") as f:
    config = json.load(f)

# get names of all servers
all_servers = [
    f"{config['servers']['hosts'][i]}:{config['servers']['ports'][i]}" for i in range(num_servers)
]

# get names of all lobbies
all_lobbies = [
    f"{config['lobbies']['lobby_hosts'][i]}:{config['lobbies']['lobby_ports'][i]}" for i in range(3)
]

# A thread-safe queue for outgoing MainRequests.
outgoing_queue = queue.Queue()
lobby_queue = queue.Queue()


def request_generator():
    """Yield MainRequests from the outgoing_queue."""
    while True:
        req = outgoing_queue.get()
        yield req

def lobby_request_generator():
    """Yield LobbyRequests from the lobby_queue."""
    while True:
        req = lobby_queue.get()
        yield req


class ClientUI:
    """
    The client UI for the messenger.

    The client UI is a tkinter application that has a few different states:
    - User Entry
    - Login
    - Register
    - Main
    - Delete

    The user entry is the first screen that asks for a username.
    The login screen asks for a username and password.
    The register screen asks for a username and password.

    The main screen has a list of users, a chat window, and a chat entry.

    The delete screen asks for a username and password to confirm deletion.

    The client UI is responsible for sending requests to the server and processing responses.
    """

    def __init__(self):
        """
        Initialize the client UI.
        """
        self.root = tk.Tk()
        self.root.title("Messenger")
        self.root.geometry("800x600")

        self.credentials = None
        self.leader_address = None
        self.stop_main_event = threading.Event()
        self.stop_lobby_event = threading.Event()
        self.players = []
        self.voted = False

        self.check_for_leader()

        self.moolah = 0

        # setup first screen
        self.setup_user_entry()

        # run the tkinter main loop
        self.root.mainloop()

    def handle_responses(self):
        """
        Constantly check for responses from the server and process them.
        """
        try:
            # responses = self.stub.Main(request_generator())
            for resp in self.responses_iter:
                logging.info(f"Size of response: {sys.getsizeof(resp)}")
                action = resp.action
                if action == main_pb2.CHECK_USERNAME:
                    # destroy current screen
                    self.destroy_user_entry()
                    # if the username exists, go to login
                    # if not, go to register
                    if not resp.result:
                        self.setup_login()
                    else:
                        self.setup_register()
                elif action == main_pb2.LOGIN:
                    # if login successful, update users and go to undelivered
                    # if not, go to login with failed
                    if resp.result:
                        self.moolah = resp.moolah
                        self.credentials = self.login_entry.get()
                        self.login_frame.destroy()
                        self.setup_main()
                    else:
                        self.login_frame.destroy()
                        self.setup_login(failed=True)
                elif action == main_pb2.REGISTER:
                    # if successful login, update users and go to main
                    # if not, go to register with failed
                    if resp.result:
                        self.moolah = resp.moolah
                        self.credentials = self.register_entry.get()
                        self.register_frame.destroy()
                        self.setup_main()
                    else:
                        self.register_username_exists_label.pack()
                elif action == main_pb2.DELETE_ACCOUNT:
                    # if successful, reset login vars and go to deleted
                    # if not, go to settings with failed
                    if resp.result:
                        self.reset_login_vars()
                        self.destroy_settings()
                        self.setup_deleted()
                    else:
                        self.destroy_settings()
                        self.setup_settings(failed=True)
                # elif action == main_pb2.JOIN_LOBBY:
                #     if resp.result:
                #         raise Exception
        except grpc.RpcError as e:
            logging.error(f"Error receiving response: {e}")
            if not self.stop_main_event.is_set():
                self.check_for_leader()

    def lobby_handle_responses(self):
        """
        Constantly check for responses from the server and process them.
        """
        try:
            for resp in self.lobby_responses_iter:
                logging.info(f"Size of response: {sys.getsizeof(resp)}")
                action = resp.action
                if action == lobby_pb2.JOIN_LOBBY:
                    # if successful, set up lobby
                    if resp.result:
                        self.destroy_main()
                        self.setup_lobby()
                    else:
                        pass
                elif action == lobby_pb2.SHOW_LOBBY:
                    self.players = resp.user_info
                    self.destroy_lobby()
                    self.setup_lobby()
                elif action == lobby_pb2.SEND_VOTE:
                    print('got a send_vote response')
                    # if successful, set up lobby
                    if resp.result:
                        self.voted = True
                        self.destroy_lobby()
                        self.setup_lobby()
                    else:
                        pass
                elif action == lobby_pb2.SHOW_GAME:
                    # if successful, set up lobby
                    if resp.result:
                        self.game_state = resp.game_state
                        # get index of self
                        self.index = np.where(
                            np.array(self.game_state.players) == self.credentials
                        )[0][0]
                        self.destroy_lobby()
                        self.setup_game()
        except grpc.RpcError as e:
            logging.error(f"Error receiving response: {e}")
            if not self.stop_main_event.is_set():
                print("uhhhhhh problem?")

    def check_for_leader(self, retries=6):
        '''
        Check for the leader of the servers.
        Retries 6 times by default.
        '''
        if retries <= 0:
            logging.error("Could not find leader.")
            sys.exit(1)
        logging.info("Checking for leader...")
        time.sleep(5)
        # we want to make sure that we are connected to the leader
        # if we are not connected OR we had errors in connecting to the leader
        # we need to ask replicas for new leader
        no_leader = True
        previous_leader = self.leader_address
        for server in all_servers:
            try:
                channel = grpc.insecure_channel(server)
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                response = stub.GetLeader(raft_pb2.GetLeaderRequest(useless=True))
                if response.leader_address:
                    logging.info(f"Leader found: {response.leader_address}")
                    logging.info(f"Info came from: {server}")
                    self.leader_address = response.leader_address
                    no_leader = False
                    break
            except grpc.RpcError as e:
                logging.error(f"Error connecting to {server}: {e}")

        if no_leader:
            self.check_for_leader(retries - 1)
            return
        if self.leader_address != previous_leader:
            # new leader
            try:
                self.request_thread.join()
                self.channel.close()
            except:
                pass
            self.channel = grpc.insecure_channel(self.leader_address)
            self.stub = main_pb2_grpc.MainServiceStub(self.channel)
            self.responses_iter = self.stub.Main(request_generator())
            self.request_thread = threading.Thread(
                target=self.handle_responses, daemon=True
            )
            self.request_thread.start()
            time.sleep(1)
            # this NEEDS to happen twice due to multiple threads
            self.send_connect_request()
            self.send_connect_request()

    def send_connect_request(self):
        """
        When a new leader is found, send a connect request to the server.
        """
        # create a request
        request = main_pb2.MainRequest(
            action=main_pb2.CONNECT, username=self.credentials
        )

        outgoing_queue.put(request)

    def reset_login_vars(self):
        """
        Reset the login variables.
        """
        self.credentials = None

    def connect_to_lobby(self, lobby = 0):
        """
        Connect to a lobby.

        Parameters
        ----------
        lobby : str
            The lobby to connect to.
        """
        self.lobby = lobby

        # close main channel
        self.stop_main_event.set()
        self.responses_iter.cancel()
        self.request_thread.join()
        self.channel.close()
        self.leader_address = None
        self.stop_main_event.clear()

        self.lobby_channel = grpc.insecure_channel(all_lobbies[lobby])
        self.lobby_stub = lobby_pb2_grpc.LobbyServiceStub(self.lobby_channel)
        self.lobby_responses_iter = self.lobby_stub.Lobby(lobby_request_generator())
        self.lobby_request_thread = threading.Thread(
            target=self.lobby_handle_responses, daemon=True
        )
        self.lobby_request_thread.start()
        time.sleep(1)

        # KG: for some reason this needs to be done twice
        request = lobby_pb2.LobbyRequest(
            action=lobby_pb2.JOIN_LOBBY, username=self.credentials
        )

        lobby_queue.put(request)

    def reconnect_to_server(self):
        """
        Reconnect to the server.
        """
        # close lobby channel
        self.stop_lobby_event.set()
        self.lobby_responses_iter.cancel()
        self.lobby_request_thread.join()
        self.lobby_channel.close()
        self.leader_address = None
        self.stop_lobby_event.clear()

        self.check_for_leader()
        self.destroy_lobby()
        self.setup_main()

    """
    Functions starting with "send_" are used to send requests to the server.

    These are used when the user interacts with the tkinter window.
    """

    def send_logreg_request(self, action, username, password, confirm_password=None):
        """
        Send a login or register request to the server, depending on the action.

        Parameters
        ----------
        action : str
            The action to take. Either "login" or "register".
        username : str
            The username to send.
        password : str
            The password to send.
        confirm_password : str
            The confirm password to send. Only used for registration.
        """
        # create a request
        request = main_pb2.MainRequest(
            action=action,
            username=username,
            passhash=password,
        )

        outgoing_queue.put(request)

    def send_user_check_request(self, username):
        """
        Send a request to check if the username exists.

        Parameters
        ----------
        username : str
            The username to check.
        """
        # create a request

        request = main_pb2.MainRequest(
            action=main_pb2.CHECK_USERNAME,
            username=username,
        )

        outgoing_queue.put(request)

    def send_delete_request(self, password):
        """
        Send a request to delete the account.
        """
        logging.info(f"Deleting Account: {self.credentials}")

        request = main_pb2.MainRequest(
            action=main_pb2.DELETE_ACCOUNT,
            username=self.credentials,
            passhash=password,
        )

        outgoing_queue.put(request)
    
    def send_join_lobby_request(self):
        """
        Send a request to join the lobby.
        """
        request = main_pb2.MainRequest(
            action=main_pb2.JOIN_LOBBY,
            username=self.credentials,
        )

        outgoing_queue.put(request)
    
    def send_lobby_vote_request(self, vote):
        """
        Send a request to vote for the game to start.
        """
        request = lobby_pb2.LobbyRequest(
            action=lobby_pb2.SEND_VOTE,
            username=self.credentials,
            vote=vote,
        )

        lobby_queue.put(request)

    """
    Functions starting with "setup_" are used to set up the state of the tkinter window.

    Each setup function has a corresponding "destroy_" function to remove the widgets from the window.
    """

    def setup_user_entry(self):
        """
        Set up the user entry screen.

        Has:
        - A label that says "Enter username:"
        - An entry for the user to enter their username.
        - A button that says "Enter" to submit the username.
        """
        self.user_entry_frame = tk.Frame(self.root)
        self.user_entry_frame.pack()
        self.user_entry_label = tk.Label(self.user_entry_frame, text="Enter username:")
        self.user_entry_label.pack()
        self.user_entry = tk.Entry(self.user_entry_frame)
        self.user_entry.pack()
        self.user_entry_button = tk.Button(
            self.user_entry_frame,
            text="Enter",
            command=lambda: (
                self.send_user_check_request(self.user_entry.get())
                if self.user_entry.get()
                else None
            ),
        )

        self.user_entry_button.pack()

    def destroy_user_entry(self):
        """
        Destroy the user entry screen.
        """
        self.user_entry_frame.destroy()

    def setup_login(self, failed=False):
        """
        Set up the login screen.

        Has:
        - A label that says "Enter your username:"
        - An entry for the user to enter their username.
        - A label that says "Enter your password:"
        - An entry for the user to enter their password.
        - A button that says "Login" to submit the login.
        - A label that says "Login failed, username/password incorrect" that is hidden by default.
        """
        self.login_frame = tk.Frame(self.root)
        self.login_frame.pack()
        self.login_label = tk.Label(self.login_frame, text="Enter your username:")
        self.login_label.pack()
        self.login_entry = tk.Entry(self.login_frame)
        self.login_entry.pack()
        self.login_password_label = tk.Label(
            self.login_frame, text="Enter your password:"
        )
        self.login_password_label.pack()
        self.login_password_entry = tk.Entry(self.login_frame)
        self.login_password_entry.pack()
        self.login_button = tk.Button(
            self.login_frame,
            text="Login",
            command=lambda: (
                self.send_logreg_request( 
                    main_pb2.LOGIN,
                    self.login_entry.get(),
                    self.login_password_entry.get(),
                )
                if self.login_entry.get() and self.login_password_entry.get()
                else None
            ),
        )
        self.login_button.pack()

        self.back_button_login = tk.Button(
            self.login_frame,
            text="Back",
            command=lambda: [self.destroy_login(), self.setup_user_entry()],
        )
        self.back_button_login.pack()

        self.login_failed_label = tk.Label(
            self.login_frame, text="Login failed, username/password incorrect"
        )

        if failed:
            self.login_failed_label.pack()

    def destroy_login(self):
        """
        Destroy the login screen.
        """
        self.login_frame.destroy()

    def setup_register(self):
        """
        Set up the register screen.

        Has:
        - A label that says "Enter your username - reg:"
        - An entry for the user to enter their username.
        - A label that says "Enter your password - reg:"
        - An entry for the user to enter their password.
        - A label that says "Confirm your password - reg:"
        - An entry for the user to confirm their password.
        - A button that says "Register" to submit the registration.
        - A label that says "Passwords do not match" that is hidden by default.
        - A label that says "Username already exists" that is hidden by default.
        """
        self.register_frame = tk.Frame(self.root)
        self.register_frame.pack()

        self.register_label = tk.Label(
            self.register_frame, text=f"Username not found: please register"
        )
        self.register_label.pack()

        self.register_username_label = tk.Label(
            self.register_frame, text="Enter a username:"
        )
        self.register_username_label.pack()
        self.register_entry = tk.Entry(self.register_frame)
        self.register_entry.pack()
        self.register_password_label = tk.Label(
            self.register_frame, text="Choose your password:"
        )
        self.register_password_label.pack()
        self.register_password_entry = tk.Entry(self.register_frame)
        self.register_password_entry.pack()

        self.register_button = tk.Button(
            self.register_frame,
            text="Register",
            command=lambda: (
                self.send_logreg_request(
                    main_pb2.REGISTER,
                    self.register_entry.get(),
                    self.register_password_entry.get(),
                )
                if self.register_entry.get() and self.register_password_entry.get()
                else None
            ),
        )
        self.register_button.pack()
        # self.register_passwords_do_not_match_label = tk.Label(
        #     self.register_frame, text="Passwords do not match"
        # )

        self.back_button_register = tk.Button(
            self.register_frame,
            text="Back",
            command=lambda: [self.destroy_register(), self.setup_user_entry()],
        )
        self.back_button_register.pack()

        self.register_username_exists_label = tk.Label(
            self.register_frame, text="Username already exists"
        )

    def destroy_register(self):
        """
        Destroy the register screen.
        """
        self.register_frame.destroy()

    def setup_main(self):
        """
        Main is set up into 3 components.

        On the left side is a list of all available users.
        - This is a listbox that is populated with all users.]
        - You can click on a user and click "Message" to start a chat with them.

        In the middle is the chat window.
        - This is a text widget that displays the chat history.
        - It is read-only.

        On the right side is the chat entry and settings.
        - It has a text entry for typing messages and a button under that says "send".
        - There is a button that says "Settings" at the bottom opens a new window.
        """
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack()

        # add settings button
        self.settings_button = tk.Button(
            self.main_frame,
            text="Settings",
            command=lambda: [self.destroy_main(), self.setup_settings()],
        )
        self.settings_button.pack(side=tk.BOTTOM)

        # add label for moolah
        self.moolah_label = tk.Label(
            self.main_frame, text=f"Your Moolah: {self.moolah}"
        )
        self.moolah_label.pack(side=tk.BOTTOM)

        # add button for connecting to lobby 1
        self.lobby1_button = tk.Button(
            self.main_frame,
            text="Connect to Lobby",
            command=lambda: self.connect_to_lobby(),
        )
        self.lobby1_button.pack(side=tk.BOTTOM)

    def destroy_main(self):
        """
        Destroy the main screen.
        """
        self.main_frame.destroy()

    def setup_lobby(self):
        print("SETTING UP LOBBY")
        print("CREDENTIALS: ", self.credentials)
        print("PLAYERS: ", self.players)
        """
        Set up the lobby 1 screen.

        Has:
        - A label that says "Lobby 1"
        - A button that says "Back" to go back to the main screen.
        """
        self.game_frame = tk.Frame(self.root)
        self.game_frame.pack()

        self.game_label = tk.Label(self.game_frame, text="Lobby 1")
        self.game_label.pack()

        # create four player slots in a row
        self.player_frames = []
        self.player_labels = []

        for i in range(4):
            slot_frame = tk.Frame(self.game_frame)
            slot_frame.pack(side=tk.LEFT, padx=10)

            # decide what text to show
            if i == 0:
                text = f"{self.credentials}\n{self.moolah}"
            elif i >= 1 and i <= len(self.players):
                text = f"{self.players[i-1].username}\n{self.players[i-1].moolah}"
                voted = "Ready" if self.players[i-1].voted_yes else "Not Ready"
            else:
                text = "waiting for player..."
                voted = ""

            lbl = tk.Label(slot_frame, text=text, width=15, height=2, relief=tk.RIDGE)
            lbl.pack()
            self.player_frames.append(slot_frame)
            self.player_labels.append(lbl)

            # add vote button under the first label
            if i == 0 and not self.voted:
                btn = tk.Button(slot_frame, text="Vote to Start", command=lambda: self.send_lobby_vote_request(True))
                btn.pack(pady=(5, 0))
            elif i == 0 and self.voted:
                # should now have label
                lbl = tk.Label(slot_frame, text="Voted to Start")
                lbl.pack(pady=(5, 0))

            # add text below lables of other players
            if i > 0:
                voted_label = tk.Label(slot_frame, text=voted)
                voted_label.pack(pady=(5, 0))

        self.back_button_game = tk.Button(
            self.game_frame,
            text="Back",
            command=lambda: self.reconnect_to_server(),
        )
        self.back_button_game.pack()

    def destroy_lobby(self):
        """
        Destroy the lobby 1 screen.
        """
        self.game_frame.destroy()

    def setup_settings(self, failed=False):
        """
        Set up the settings screen.

        Has a button that says "Delete Account" that opens a new window.

        Parameters
        ----------
        failed : bool
            Whether the delete failed. If so, show a label that says "Failed to delete account, password incorrect".
        """
        self.settings_frame = tk.Frame(self.root)
        self.settings_frame.pack()

        self.connected_to = None

        if failed:
            self.delete_failed_label = tk.Label(
                self.settings_frame, text="Failed to delete account, password incorrect"
            )
            self.delete_failed_label.pack()

        self.delete_label = tk.Label(
            self.settings_frame,
            text="Are you sure you want to delete your account?\n(Enter password to confirm)",
        )
        self.delete_label.pack()

        self.confirm_password_label = tk.Label(
            self.settings_frame, text="Enter your password:"
        )
        self.confirm_password_label.pack()

        self.confirm_password_entry = tk.Entry(self.settings_frame)
        self.confirm_password_entry.pack()

        self.delete_button = tk.Button(
            self.settings_frame,
            text="Delete",
            command=lambda: (
                self.send_delete_request(self.confirm_password_entry.get())
                if self.confirm_password_entry.get()
                else None
            ),
        )
        self.delete_button.pack()
        self.cancel_button = tk.Button(
            self.settings_frame,
            text="Cancel",
            command=lambda: [self.destroy_settings(), self.setup_main()],
        )
        self.cancel_button.pack()

    def destroy_settings(self):
        """
        Destroy the settings screen.
        """
        self.settings_frame.destroy()

    def setup_deleted(self):
        """
        Set up the screen that shows the account has been deleted.
        """
        self.deleted_frame = tk.Frame(self.root)
        self.deleted_frame.pack()

        self.deleted_label = tk.Label(
            self.deleted_frame, text="Account successfully deleted."
        )
        self.deleted_label.pack()

        self.go_home_button = tk.Button(
            self.deleted_frame,
            text="Go to Home",
            command=lambda: [self.destroy_deleted(), self.setup_user_entry()],
        )
        self.go_home_button.pack()

    def destroy_deleted(self):
        """
        Destroy the deleted screen.
        """
        self.deleted_frame.destroy()

    def setup_game(self):
        # create a fresh frame for the game
        self.game_frame = tk.Frame(self.root)
        self.game_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # ── Top: show other players with their moolah and current bet ──
        opponents_frame = tk.Frame(self.game_frame)
        opponents_frame.pack(side=tk.TOP, pady=(0,10))
        for idx, uname in enumerate(self.game_state.players):
            if uname == self.credentials:
                continue
            # assuming parallel lists .moolahs and .bets in game_state
            m = self.game_state.money[idx]
            b = self.game_state.bets[idx]
            slot = tk.Frame(opponents_frame, bd=1, relief=tk.RIDGE, padx=5, pady=5)
            slot.pack(side=tk.LEFT, padx=10)
            tk.Label(slot, text=f"{uname}\nMoolah: {m}\nBet: {b}", width=15, height=3).pack()

        # ── Middle: community cards (the “river”) ──
        river_frame = tk.Frame(self.game_frame)
        river_frame.pack(side=tk.TOP, pady=(0,10))
        tk.Label(river_frame, text="Community Cards:").pack()
        cards = " ".join(self.game_state.river_cards)
        tk.Label(river_frame, text=cards).pack()

        # ── Pot ──
        pot_frame = tk.Frame(self.game_frame)
        pot_frame.pack(side=tk.TOP, pady=(0,10))
        tk.Label(pot_frame, text=f"Pot: {self.game_state.pot}").pack()

        # ── Your cards ──
        hand_frame = tk.Frame(self.game_frame)
        hand_frame.pack(side=tk.TOP, pady=(0,10))
        tk.Label(hand_frame, text="Your Cards:").pack()
        # self.index was set to your player index in SHOW_GAME handling
        current_cards = self.game_state.hand_cards[self.index]
        curr_cards = []
        if self.game_state.game_type == lobby_pb2.TEXAS:
            # show the first two cards
            curr_cards = [current_cards.card1, current_cards.card2]
        else:
            # show all cards, 5 card draw
            curr_cards = [current_cards.card1, current_cards.card2, current_cards.card3, 
                     current_cards.card4, current_cards.card5]

        cards = " ".join(curr_cards)
        tk.Label(hand_frame, text=cards).pack()

        # ── Bottom: action buttons, only if it's your turn ──
        if self.game_state.current_player == self.credentials:
            actions_frame = tk.Frame(self.game_frame)
            actions_frame.pack(side=tk.TOP, pady=(0,10))
            tk.Button(actions_frame, text="Fold",
                  command=lambda: self.send_game_action("FOLD")).pack(side=tk.LEFT, padx=5)
            tk.Button(actions_frame, text="Call",
                  command=lambda: self.send_game_action("CALL")).pack(side=tk.LEFT, padx=5)
            tk.Button(actions_frame, text="Raise",
                  command=lambda: self.send_game_action("RAISE", self.raise_amount.get())).pack(side=tk.LEFT, padx=5)
            # add number box to raise
            self.raise_amount = tk.Entry(actions_frame)
            self.raise_amount.pack(side=tk.LEFT, padx=5)
            self.raise_amount.insert(0, "Enter raise amount")




"""
The rest of the code is for setting up the connection and running the client.
"""


if len(sys.argv) != 1:
    logging.error("Usage: python client.py")
    sys.exit(1)

if __name__ == "__main__":
    client_ui = ClientUI()
