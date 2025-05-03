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
players = {}


# params for lobby
SUITS = ['\u2660', '\u2665', '\u2666', '\u2663']  # Spades, Hearts, Diamonds, Clubs
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
RANK_VALUE = {r: i + 2 for i, r in enumerate(RANKS)}
game_started = False
game_type = lobby_pb2.TEXAS  # default game type

class Deck:
    """Standard 52‑card deck"""

    def __init__(self):
        self.cards = [f'{rank}{suit}' for suit in SUITS for rank in RANKS]
        random.shuffle(self.cards)

    def deal(self, n=1):
        return [self.cards.pop() for _ in range(n)]
    
    def shuffle(self):
        random.shuffle(self.cards)

    def reshuffle(self):
        self.cards = [f'{rank}{suit}' for suit in SUITS for rank in RANKS]
        random.shuffle(self.cards)


class Player:
    """
    Player class for the lobby server.

    This class represents a player in the lobby server.
    """

    def __init__(self, username, user_queue):
        # buyin is 100 chips
        self.money = 100
        self.username = username
        self.queue = user_queue

        # for starting the game
        self.voted_yes = False

        # for playing the game
        self.hand = []
        self.folded = False
        self.current_bet = 0

    def send_message(self, message):
        self.queue.put(message)

    def reset_for_round(self):
        self.hand = []
        self.folded = False
        self.current_bet = 0
        self.voted_yes = False

    def get_user_information(self):
        return lobby_pb2.UserInformation(
            username=self.username,
            voted_yes=self.voted_yes,
            moolah=self.money,
        )
    
    def send_game_state(self, game_state):
        self.queue.put(
            lobby_pb2.LobbyResponse(
                action=lobby_pb2.SHOW_GAME,
                result=True,
                game_state=game_state
            )
        )
    

class TexasHoldem:
    """
    Game class for the lobby server.

    This class represents a game in the lobby server.
    """

    def __init__(self):
        self.deck = Deck()
        self.players = []
        self.money = []
        self.bets = []
        # for call vs check
        self.delta_bet = 0
        self.round = 0
        self.big_blind = 0
        self.small_blind = 1
        self.pot = 0
        self.phase = 0
        self.player_pointer = 0

    def load_players(self, players):
        for player in players.values():
            self.players.append(player)
            self.money.append(100)

    def reset_for_round(self):
        self.round += 1
        if self.round >= 8:
            self.end()

        self.deck.reshuffle()
        for player in self.players:
            player.reset_for_round()
        
        self.big_blind = (self.big_blind + 1) % len(self.players)
        self.small_blind = (self.small_blind + 1) % len(self.players)

    def get_game_state(self):
        global game_type
        return lobby_pb2.GameState(
            players = [
                player.username for player in self.players
            ],
            money = [
                player.money for player in self.players
            ],
            bets = [
                player.current_bet for player in self.players
            ],
            river_cards = [],
            current_player = self.players[self.player_pointer].username,
            hand_cards = [
                player.hand for player in self.players
            ],
            pot = self.pot,
            small_blind = self.small_blind,
            big_blind = self.big_blind,
            game_round = self.round,
            game_type = game_type,
            folded = [
                player.folded for player in self.players
            ],
        )

    def start(self):
        global game_started
        self.load_players(players)
        self.reset_for_round()
        # make big blind bet 2, small blind bet 1
        self.players[self.big_blind].current_bet = 2
        self.players[self.small_blind].current_bet = 1
        self.pot = 3

        game_started = True
        for player in self.players:
            # deal each player 2 cards
            cards = self.deck.deal(2)
            player.hand = lobby_pb2.HandCards(
                card1=cards[0],
                card2=cards[1]
            )
        for player in self.players:
            # give all players the current game state
            player.send_game_state(
                self.get_game_state()
            )

    def advance_phase(self):
        # advance the game phase
        if self.phase == 0:
            # deal the flop
            self.river = self.deck.deal(3)
            self.phase = 1
        elif self.phase == 1:
            # deal the turn
            self.river.append(self.deck.deal(1)[0])
            self.phase = 2
        elif self.phase == 2:
            # deal the river
            self.river.append(self.deck.deal(1)[0])
            self.phase = 3
        elif self.phase == 3:
            # end the game
            self.end()
    
    def play_next(self, play):
        pass

    def end(self):
        global game_started
        game_started = False
        

class LobbyServiceServicer(lobby_pb2_grpc.LobbyServiceServicer):
    """
    MainServiceServicer class for MainServiceServicer

    This class handles the main chat functionality of the server, sending responses via queues.
    All log messages in this service begin with [MAIN].
    """
    global game_started, game_type

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
                        new_player = Player(req.username, client_queue)
                        if (req.username != "") and (req.username not in players):
                            players[new_player.username] = new_player
                            username = req.username
                        client_queue.put(
                            lobby_pb2.LobbyResponse(
                                action=lobby_pb2.JOIN_LOBBY, result=True
                            )
                        )
                        for player in players.values():
                            other_users = [
                                p.get_user_information() for p in players.values() if p.username != player.username
                            ]

                            player.send_message(
                                lobby_pb2.LobbyResponse(
                                    action=lobby_pb2.SHOW_LOBBY,
                                    result=True,
                                    user_info=other_users,
                                )
                            )
                    elif req.action == lobby_pb2.SEND_VOTE:
                        if username in players:
                            player = players[username]
                            player.voted_yes = req.vote

                            player.send_message(
                                lobby_pb2.LobbyResponse(
                                    action=lobby_pb2.SEND_VOTE,
                                    result=True
                                )
                            )

                            # update all players
                            for player in players.values():
                                other_users = [
                                    p.get_user_information() for p in players.values() if p.username != player.username
                                ]
                                player.send_message(
                                    lobby_pb2.LobbyResponse(
                                        action=lobby_pb2.SHOW_LOBBY,
                                        result=True,
                                        user_info=other_users,
                                    )
                                )
                            if all(p.voted_yes for p in players.values()) and len(players) >= 2:
                                # start the game
                                game = TexasHoldem()
                                game.start()


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
                if username in players:
                    del players[username]
                    # update all players
                    for player in players.values():
                        other_users = [
                            p.get_user_information() for p in players.values() if p.username != player.username
                        ]
                        player.send_message(
                            lobby_pb2.LobbyResponse(
                                action=lobby_pb2.SHOW_LOBBY,
                                result=True,
                                user_info=other_users,
                            )
                        )
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
    
    def GetLobbyInfo(self, request, context):
        return lobby_pb2.ServerResponse(
            active = game_started,
            num_players = len(players),
            game_type = game_type,
        )

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
