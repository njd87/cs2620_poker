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


# params the game


class Deck:
    """Standard 52‑card deck"""

    def __init__(self):
        self.SUITS = ['\u2660', '\u2665', '\u2666', '\u2663']  # Spades, Hearts, Diamonds, Clubs
        self.RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
        self.RANK_VALUE = {r: i + 2 for i, r in enumerate(self.RANKS)}
        self.cards = [f'{rank}{suit}' for suit in self.SUITS for rank in self.RANKS]
        random.shuffle(self.cards)

    def deal(self, n=1):
        return [self.cards.pop() for _ in range(n)]
    
    def shuffle(self):
        random.shuffle(self.cards)

    def reshuffle(self):
        self.cards = [f'{rank}{suit}' for suit in self.SUITS for rank in self.RANKS]
        random.shuffle(self.cards)
    

class TestTexasHoldem:
    """
    Game class for the lobby server.

    This class represents a game in the lobby server.
    """

    def __init__(self):
        self.SUITS = ['\u2660', '\u2665', '\u2666', '\u2663']  # Spades, Hearts, Diamonds, Clubs
        self.RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
        self.RANK_VALUE = {r: i + 2 for i, r in enumerate(self.RANKS)}
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
        # parse cards
        ranks = [self.RANK_VALUE[c[0]] for c in cards]
        suits = [c[1] for c in cards]
        counts = Counter(ranks)
        # sort cards
        counts_items = sorted(counts.items(), key=lambda x: (-x[1], -x[0]))

        # check for flush
        is_flush = len(set(suits)) == 1

        # check straight for straight (including wheel A-2-3-4-5)
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

        # hand category
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

        # tiebreakers to length 5
        tiebreak += [0] * (5 - len(tiebreak))

        # compute numeric rank
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
        # load the players into the game
        for player in players.values():
            self.players.append(player)
            self.money.append(100)
        self.active_players = len(self.players)

    def reset_for_round(self):
        # reset all params
        self.round += 1
        if self.round > 5 or any(player.money <= 0 for player in self.players):
            # game is over
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
            self.check_count = 0
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

        # while the player pointer points to a folded player, move to the next player
        while self.players[self.player_pointer].folded:
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
        # game has ended, update main and kick all players
        global game_started, outgoing_queue, game_type
        game_started = False
        # close connections to all players
        for player in self.players:
            player.send_message(
                lobby_pb2.LobbyResponse(
                    action=lobby_pb2.KICK_PLAYER,
                    result=True,
                    )
                )
            outgoing_queue.put(
                main_pb2.MainRequest(
                    action=main_pb2.SAVE_GAME,
                    game_history=main_pb2.GameHistoryEntry(
                        game_type=game_type,
                        player=player.username,
                        money_won = player.money - 100,
                    )
                )
            )

        # clear players
        global players
        players = {}
        
        self.reset_params()


class TestFiveCardDraw:
    """
    Game class for the lobby server.

    This class represents a game in the lobby server.
    """

    def __init__(self):
        self.SUITS = ['\u2660', '\u2665', '\u2666', '\u2663']  # Spades, Hearts, Diamonds, Clubs
        self.RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
        self.RANK_VALUE = {r: i + 2 for i, r in enumerate(self.RANKS)}
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
        self.can_exchange = []
    
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
        # parse ranks and suits
        ranks = [self.RANK_VALUE[c[0]] for c in cards]
        suits = [c[1] for c in cards]
        counts = Counter(ranks)
        # sort
        counts_items = sorted(counts.items(), key=lambda x: (-x[1], -x[0]))

        # flush
        is_flush = len(set(suits)) == 1

        # straight
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

        # tiebreakers
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

        # tiebreakers to length 5
        tiebreak += [0] * (5 - len(tiebreak))

        # compute numeric rank
        value = category * (14 ** 5)
        for i, v in enumerate(tiebreak):
            value += v * (14 ** (4 - i))
        return value
    
    def evaluate_hand(self, cards):
        # helper function, given that this class is based on the texas holdem class
        return self.evaluate_5cards(cards)

    def load_players(self, players):
        for player in players.values():
            self.players.append(player)
            self.money.append(100)
        self.active_players = len(self.players)
        self.can_exchange = [False] * len(self.players)

    def reset_for_round(self):
        self.round += 1
        if self.round > 5 or any(player.money <= 0 for player in self.players):
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
            can_exchange = self.can_exchange,
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
            cards = self.deck.deal(5)
            player.hand = lobby_pb2.HandCards(
                card1=cards[0],
                card2=cards[1],
                card3=cards[2],
                card4=cards[3],
                card5=cards[4]
            )
        for player in self.players:
            # give all players the current game state
            player.send_game_state(
                self.get_game_state()
            )

    def advance_phase(self):
        self.check_count = 0
        # advance the game phase
        if self.phase == 0:
            # allow all players to exchange cards
            self.phase = 1
            self.can_exchange = [True] * len(self.players)
        elif self.phase == 1:
            # determine winner
            self.phase = 2
            # evaluate the winner
            active_players = [player for player in self.players if not player.folded]
            best_hand = 0
            best_players = []
            for player in active_players:
                cards = [player.hand.card1, player.hand.card2, player.hand.card3, player.hand.card4, player.hand.card5]
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
            self.check_count = 0
        elif action == lobby_pb2.CHECK_CALL:
            self.check_count += 1
            # if min_bet is greater than or equal to the player's money, set the bet to the player's money
            if self.min_bet >= self.players[self.player_pointer].money:
                self.players[self.player_pointer].current_bet = self.players[self.player_pointer].money
            else:
                self.players[self.player_pointer].current_bet = max(self.min_bet, self.players[self.player_pointer].current_bet)
                self.min_bet = self.players[self.player_pointer].current_bet
        elif action == lobby_pb2.EXCHANGE:
            # exchange cards
            player = self.players[self.player_pointer]
            for i, can_exchange_indicator in enumerate(play.card_exchange_idx):
                if can_exchange_indicator:
                    # exchange the card
                    exec(f'player.hand.card{i+1} = self.deck.deal(1)[0]')
                
            self.can_exchange[self.player_pointer] = False
            self.check_count = 0


        self.pot = sum(
                [player.current_bet for player in self.players]
        )
        self.player_pointer = (self.player_pointer + 1) % len(self.players)

        # while the player pointer points to a folded player, move to the next player
        while self.players[self.player_pointer].folded:
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
        global game_started, outgoing_queue, game_type
        game_started = False
        # close connections to all players
        for player in self.players:
            player.send_message(
                lobby_pb2.LobbyResponse(
                    action=lobby_pb2.KICK_PLAYER,
                    result=True,
                    )
                )
            outgoing_queue.put(
                main_pb2.MainRequest(
                    action=main_pb2.SAVE_GAME,
                    game_history=main_pb2.GameHistoryEntry(
                        game_type=game_type,
                        player=player.username,
                        money_won = player.money - 100,
                    )
                )
            )

        global players
        players = {}
        '''
        send game result to main server
        '''
        
        self.reset_params()