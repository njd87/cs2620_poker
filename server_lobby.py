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
import itertools
from collections import Counter

import lobby_pb2_grpc
import lobby_pb2
import main_pb2_grpc
import main_pb2
import raft_pb2_grpc
import raft_pb2

import json
import traceback

'''
Making sure the server is started with the correct arguments.
'''

num_servers = 2

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

# get names of all servers
all_servers = [
    f"{config['servers']['hosts'][i]}:{config['servers']['ports'][i]}" for i in range(num_servers)
]

credentials = None
leader_address = None

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
game = None

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
        print('Sending game state to player', self.username)
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
        self.min_bet = 0
        self.round = 0
        self.big_blind = 0
        self.small_blind = 1
        self.pot = 0
        self.phase = 0
        self.player_pointer = 0
        self.check_count = 0
        self.active_players = 0
        self.river = []
    
    def reset_params(self):
        self.deck = Deck()
        self.players = []
        self.money = []
        self.bets = []
        # for call vs check
        self.min_bet = 0
        self.round = 0
        self.big_blind = 0
        self.small_blind = 1
        self.pot = 0
        self.phase = 0
        self.player_pointer = 0
        self.check_count = 0
        self.active_players = 0
        self.river = []

    def evaluate_5cards(self, cards):
        """
        Evaluate a 5-card poker hand, returning a numeric value where higher means stronger.
        Hand categories (0-8): high card, pair, two pair, three of a kind, straight,
        flush, full house, four of a kind, straight flush.
        """
        # Parse ranks and suits
        ranks = [RANK_VALUE[c[0]] for c in cards]
        suits = [c[1] for c in cards]
        counts = Counter(ranks)
        # Sort by frequency, then by rank
        counts_items = sorted(counts.items(), key=lambda x: (-x[1], -x[0]))

        # Check for flush
        is_flush = len(set(suits)) == 1

        # Check for straight (including wheel A-2-3-4-5)
        unique_ranks = sorted(set(ranks))
        if len(unique_ranks) == 5 and unique_ranks[-1] - unique_ranks[0] == 4:
            is_straight = True
            straight_high = unique_ranks[-1]
        elif unique_ranks == [2, 3, 4, 5, 14]:  # wheel
            is_straight = True
            straight_high = 5
        else:
            is_straight = False
            straight_high = None

        # Determine hand category and tiebreakers
        if is_straight and is_flush:
            category = 8
            tiebreak = [straight_high]
        elif counts_items[0][1] == 4:
            category = 7
            four = counts_items[0][0]
            kicker = [r for r in ranks if r != four][0]
            tiebreak = [four, kicker]
        elif counts_items[0][1] == 3 and counts_items[1][1] == 2:
            category = 6
            three = counts_items[0][0]
            pair = counts_items[1][0]
            tiebreak = [three, pair]
        elif is_flush:
            category = 5
            tiebreak = sorted(ranks, reverse=True)
        elif is_straight:
            category = 4
            tiebreak = [straight_high]
        elif counts_items[0][1] == 3:
            category = 3
            three = counts_items[0][0]
            kickers = sorted([r for r in ranks if r != three], reverse=True)
            tiebreak = [three] + kickers
        elif counts_items[0][1] == 2 and counts_items[1][1] == 2:
            category = 2
            high_pair = counts_items[0][0]
            low_pair = counts_items[1][0]
            kicker = [r for r in ranks if r not in (high_pair, low_pair)][0]
            tiebreak = [high_pair, low_pair, kicker]
        elif counts_items[0][1] == 2:
            category = 1
            pair = counts_items[0][0]
            kickers = sorted([r for r in ranks if r != pair], reverse=True)
            tiebreak = [pair] + kickers
        else:
            category = 0
            tiebreak = sorted(ranks, reverse=True)

        # Pad tiebreakers to length 5
        tiebreak += [0] * (5 - len(tiebreak))

        # Compute overall numeric rank
        # Use base 14 for each kicker slot
        value = category * (14 ** 5)
        for i, v in enumerate(tiebreak):
            value += v * (14 ** (4 - i))
        return value


    def evaluate_hand(self, cards):
        """
        Given 7 cards, evaluate the best 5-card hand and return its numeric strength.
        Higher numbers indicate stronger hands.
        """
        best_val = 0
        for combo in itertools.combinations(cards, 5):
            val = self.evaluate_5cards(combo)
            if val > best_val:
                best_val = val
        return best_val

    def load_players(self, players):
        for player in players.values():
            self.players.append(player)
            self.money.append(100)
        self.active_players = len(self.players)

    def reset_for_round(self):
        self.round += 1
        if self.round > 1:
            self.end()
            return

        self.deck.reshuffle()
        self.river = []
        self.min_bet = 0
        self.check_count = 0
        self.pot = 0
        self.phase = 0
        self.active_players = len(self.players)


        for player in self.players:
            player.reset_for_round()
        
        self.big_blind = (self.big_blind + 1) % len(self.players)
        self.small_blind = (self.small_blind + 1) % len(self.players)

        self.player_pointer = self.small_blind
        self.start_round()

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
            river_cards = self.river,
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
            min_bet = self.min_bet,
        )
    
    def start(self):
        global game_started
        game_started = True
        self.load_players(players)
        self.reset_for_round()
        self.start_round()

    def start_round(self):
        # make big blind bet 2, small blind bet 1
        self.players[self.big_blind].current_bet = min(2, self.players[self.big_blind].money)
        self.players[self.small_blind].current_bet = 1
        self.pot = self.players[self.big_blind].current_bet + self.players[self.small_blind].current_bet

        for player in self.players:
            # deal each player 2 cards
            cards = self.deck.deal(2)
            player.hand = lobby_pb2.HandCards(
                card1=cards[0],
                card2=cards[1]
            )
        for player in self.players:
            print('sending game state to player', player.username, 'from start_round')
            # give all players the current game state
            player.send_game_state(
                self.get_game_state()
            )

    def advance_phase(self):
        self.check_count = 0
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
            print('Evaluating winner...')
            # evaluate the winner
            active_players = [player for player in self.players if not player.folded]
            best_hand = 0
            best_players = []
            for player in active_players:
                cards = [player.hand.card1, player.hand.card2] + self.river
                player_eval = self.evaluate_hand(cards)
                if player_eval > best_hand:
                    best_hand = player_eval
                    best_players = [player]
                elif player_eval == best_hand:
                    best_players.append(player)

            # if there is a tie, split the pot
            if len(best_players) > 1:
                split_pot = self.pot // len(best_players)
                for player in best_players:
                    player.money += split_pot
            else:
                best_player = best_players[0]
                # give the pot to the winner
                best_player.money += self.pot

            # subtract current bets from all players
            for player in self.players:
                player.money -= player.current_bet
                player.current_bet = 0

            self.reset_for_round()



    def tell_all_players(self):
        # send game state to all players
        for player in self.players:
            print('sending game state to player', player.username, 'from tell_all_players')
            player.send_game_state(
                self.get_game_state()
            )
    
    def play_next(self, play):
        # play is conducted by the current player
        action = play.player_action
        if action == lobby_pb2.FOLD:
            self.players[self.player_pointer].folded = True
            self.active_players -= 1
        elif action == lobby_pb2.RAISE:
            amount_to_add = play.amount
            self.players[self.player_pointer].current_bet = self.min_bet + amount_to_add
            self.min_bet = self.players[self.player_pointer].current_bet
        elif action == lobby_pb2.CHECK_CALL:
            self.check_count += 1
            # if min_bet is greater than or equal to the player's money, set the bet to the player's money
            if self.min_bet >= self.players[self.player_pointer].money:
                self.players[self.player_pointer].current_bet = self.players[self.player_pointer].money
            else:
                self.players[self.player_pointer].current_bet = max(self.min_bet, self.players[self.player_pointer].current_bet)
                self.min_bet = self.players[self.player_pointer].current_bet

        self.pot = sum(
                [player.current_bet for player in self.players]
        )
        self.player_pointer = (self.player_pointer + 1) % len(self.players)
        
        # check if all active players have the same current bet
        if self.active_players == 1:
            # give the pot to the last player
            for player in self.players:
                if not player.folded:
                    player.money += self.pot
                    break
            # take away the current bets from all players
            for player in self.players:
                player.money -= player.current_bet
                player.current_bet = 0
            self.reset_for_round()
        elif all(player.current_bet == self.min_bet for player in self.players if not player.folded) and self.check_count >= self.active_players:
            # advance the phase
            self.advance_phase()
        
        self.tell_all_players()

    def end(self):
        global game_started
        game_started = False
        # close connections to all players
        for player in self.players:
            player.send_message(
                lobby_pb2.LobbyResponse(
                    action=lobby_pb2.KICK_PLAYER,
                    result=True,
                    )
                )

        global players
        players = {}
        self.reset_params()

        

class LobbyServiceServicer(lobby_pb2_grpc.LobbyServiceServicer):
    """
    LobbyServiceServicer class for LobbyServiceServicer

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
            global log, current_term, game
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
                    elif req.action == lobby_pb2.PLAY_MOVE:
                        game.play_next(req)


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

def handle_responses(responses_iter):
    """
    Constantly check for responses from the server and process them.
    """
    try:
        for resp in responses_iter:
            logging.info(f"Size of response: {sys.getsizeof(resp)}")
            action = resp.action
            if action == main_pb2.CHECK_USERNAME:
                pass
    except grpc.RpcError as e:
        logging.error(f"Error receiving response: {e}")
        check_for_leader()

def check_for_leader(retries=6):
    '''
    Check for the leader of the servers.
    Retries 6 times by default.
    '''
    global leader_address
    if retries <= 0:
        logging.error("Could not find leader.")
        sys.exit(1)
    logging.info("Checking for leader...")
    time.sleep(5)
    # we want to make sure that we are connected to the leader
    # if we are not connected OR we had errors in connecting to the leader
    # we need to ask replicas for new leader
    no_leader = True
    previous_leader = leader_address
    for server in all_servers:
        try:
            channel = grpc.insecure_channel(server)
            stub = raft_pb2_grpc.RaftServiceStub(channel)
            response = stub.GetLeader(raft_pb2.GetLeaderRequest(useless=True))
            if response.leader_address:
                logging.info(f"Leader found: {response.leader_address}")
                logging.info(f"Info came from: {server}")
                leader_address = response.leader_address
                no_leader = False
                break
        except grpc.RpcError as e:
            logging.error(f"Error connecting to {server}: {e}")

    if no_leader:
        check_for_leader(retries - 1)
        return
    if leader_address != previous_leader:
        # new leader
        try:
            request_thread.join()
            channel.close()
        except:
            pass
        channel = grpc.insecure_channel(leader_address)
        stub = main_pb2_grpc.MainServiceStub(channel)
        responses_iter = stub.Main(request_generator())
        request_thread = threading.Thread(
            target=handle_responses, args=(responses_iter,), daemon=True
        )
        request_thread.start()
        time.sleep(1)
        # this NEEDS to happen twice due to multiple threads
        send_connect_request()
        send_connect_request()

outgoing_queue = queue.Queue()
def request_generator():
    """Yield MainRequests from the outgoing_queue."""
    while True:
        req = outgoing_queue.get()
        yield req

def send_connect_request():
    """
    When a new leader is found, send a connect request to the server.
    """
    # create a request
    request = main_pb2.MainRequest(
        action=main_pb2.CONNECT_LOBBY, username=str(idx) # KG: prevent users from signing up with the same username
    )

    outgoing_queue.put(request)

if __name__ == "__main__":
    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()
    check_for_leader()
    server_thread.join()
