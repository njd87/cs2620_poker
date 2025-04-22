#!/usr/bin/env python3
"""
Command‑line Texas Hold 'Em Poker
─────────────────────────────────
• Human + 2‑4 CPU opponents
• $200 starting stacks, $1 / $2 blinds
• Plays until one player remains with chips

This is a **single‑file** implementation; just save as
    texas_holdem_cli.py
and run
    python texas_holdem_cli.py

The program prints your hole cards right after they are dealt and
reminds you of them on every street.
"""

import random
import itertools
import operator
import sys
from collections import Counter, namedtuple

# ─── Card / Deck ────────────────────────────────────────────────────────────────
RANKS = "23456789TJQKA"
SUITS = "♠♥♦♣"  # purely cosmetic – change to "SHDC" if your terminal can't show symbols
CARD_INT = {r: i for i, r in enumerate(RANKS, 2)}  # 2→14
Card = namedtuple("Card", "rank suit")

def new_deck():
    deck = [Card(r, s) for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck

# ─── Hand evaluation (7 → 5 cards) ──────────────────────────────────────────────

def evaluate_5(cards):
    """Return (category, tie_breaker_tuple) where larger is stronger."""
    ranks = sorted((CARD_INT[c.rank] for c in cards), reverse=True)
    counts = Counter(ranks)
    common = counts.most_common
    is_flush = len({c.suit for c in cards}) == 1
    # straight incl. wheel A‑5
    sorted_r = sorted(set(ranks), reverse=True)
    is_low_straight = sorted_r == [14, 5, 4, 3, 2]
    is_straight = (len(counts) == 5 and (max(ranks) - min(ranks) == 4)) or is_low_straight

    # Categories (9 high → 0 low)
    if is_straight and is_flush:
        return (9 if max(ranks) == 14 and min(ranks) == 10 else 8, max(ranks) if not is_low_straight else 5)
    if 4 in counts.values():  # four‑of‑a‑kind
        quad = next(r for r, c in counts.items() if c == 4)
        kicker = max(r for r, c in counts.items() if c == 1)
        return (7, (quad, kicker))
    if sorted(counts.values()) == [2, 3]:  # full house
        trip = next(r for r, c in counts.items() if c == 3)
        pair = next(r for r, c in counts.items() if c == 2)
        return (6, (trip, pair))
    if is_flush:
        return (5, tuple(ranks))
    if is_straight:
        return (4, max(ranks) if not is_low_straight else 5)
    if 3 in counts.values():
        trip = next(r for r, c in counts.items() if c == 3)
        kickers = sorted((r for r, c in counts.items() if c == 1), reverse=True)
        return (3, (trip, *kickers))
    if list(counts.values()).count(2) == 2:  # two pair
        pairs = sorted((r for r, c in counts.items() if c == 2), reverse=True)
        kicker = next(r for r, c in counts.items() if c == 1)
        return (2, (*pairs, kicker))
    if 2 in counts.values():  # one pair
        pair = next(r for r, c in counts.items() if c == 2)
        kickers = sorted((r for r, c in counts.items() if c == 1), reverse=True)
        return (1, (pair, *kickers))
    return (0, tuple(ranks))  # high card


def best_of_seven(seven_cards):
    return max((evaluate_5(c) for c in itertools.combinations(seven_cards, 5)))

# ─── Player class ───────────────────────────────────────────────────────────────

class Player:
    def __init__(self, name: str, stack: int, is_human: bool):
        self.name = name
        self.stack = stack
        self.is_human = is_human
        self.reset()

    def reset(self):
        self.hole: list[Card] = []
        self.in_hand: bool = self.stack > 0
        self.bet: int = 0

    def __repr__(self):
        return f"{self.name} (${self.stack})"

    # Very naive CPU strategy for demo purposes
    def decide(self, to_call: int, pot: int, stage: str):
        strength = random.random()
        if to_call == 0:
            if strength > 0.8 and self.stack >= 4:
                return "raise", 4  # minish raise
            return "check", 0
        # facing a bet
        if to_call <= min(4, self.stack) and strength > 0.3:
            return "call", to_call
        return "fold", 0

# ─── Game engine ───────────────────────────────────────────────────────────────

class Holdem:
    SMALL, BIG = 1, 2

    def __init__(self, num_cpus: int):
        self.players: list[Player] = [Player("You", 200, True)] + [Player(f"CPU {i}", 200, False) for i in range(1, num_cpus + 1)]
        self.button = 0  # dealer index rotates after every hand

    # Helper: players still with chips
    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def rotate(self):
        self.button = (self.button + 1) % len(self.players)

    # ── Public entry point ─────────────────────────────────────────────────────
    def play(self):
        while len(self.alive()) > 1:
            self.play_hand()
            self.rotate()
        print("\n🏆  {} wins the table with ${}!".format(self.alive()[0].name, self.alive()[0].stack))

    # ── One complete hand ─────────────────────────────────────────────────────
    def play_hand(self):
        deck = new_deck()
        pot = 0
        print("\n" + "=" * 40)
        print(f"Dealer ➜ {self.players[self.button].name}")

        # reset per‑hand state
        for p in self.players:
            p.reset()

        # post blinds
        sb = self.players[(self.button + 1) % len(self.players)]
        bb = self.players[(self.button + 2) % len(self.players)]
        for blind, amt in [(sb, self.SMALL), (bb, self.BIG)]:
            real = min(amt, blind.stack)
            blind.stack -= real
            blind.bet += real
            pot += real
        to_call = self.BIG

        # deal two hole cards each (round Robin)
        for _ in range(2):
            for p in self.players:
                if p.stack >= 0:  # include busted? irrelevant
                    p.hole.append(deck.pop())

        # Show your own cards once – and store reference for quick access
        human = next(pl for pl in self.players if pl.is_human)
        print("Your cards:", " ".join(c.rank + c.suit for c in human.hole))

        # Betting & community cards
        community: list[Card] = []
        stages = ["Pre‑flop", "Flop", "Turn", "River"]
        for street in range(4):
            if street == 1:  # flop
                community += [deck.pop() for _ in range(3)]
            elif street >= 2:  # turn/river
                community.append(deck.pop())

            print(f"\n{stages[street]} {'-' * 20}")
            if community:
                print("Board:", " ".join(c.rank + c.suit for c in community))
            # always remind human
            print("Your cards:", " ".join(c.rank + c.suit for c in human.hole))

            to_call = self.betting_round((self.button + 3) % len(self.players), to_call, pot)
            pot = sum(p.bet for p in self.players)
            if sum(p.in_hand for p in self.players) == 1:
                break  # only one left, no more streets

        # Showdown / pot award
        remaining = [p for p in self.players if p.in_hand]
        if len(remaining) == 1:
            winner = remaining[0]
            print(f"\n{winner.name} wins uncontested pot of ${pot} (everyone else folded)")
            winner.stack += pot
        else:
            ranked = sorted(((best_of_seven(p.hole + community), p) for p in remaining), key=operator.itemgetter(0), reverse=True)
            best_rank = ranked[0][0]
            winners = [p for r, p in ranked if r == best_rank]
            share = pot // len(winners)
            for w in winners:
                w.stack += share
            print("\nShowdown:")
            for p in remaining:
                print(f"{p.name:<6}: {' '.join(c.rank + c.suit for c in p.hole)}")
            print("🏆  " + " & ".join(w.name for w in winners) + f" win(s) ${share} each!")

        # clear bets
        for p in self.players:
            p.bet = 0

    # ── Single betting street ─────────────────────────────────────────────────
    def betting_round(self, start_idx: int, to_call: int, pot: int):
        idx = start_idx
        acted = {p: False for p in self.players if p.in_hand and p.stack > 0}

        while True:
            p = self.players[idx]
            if p.in_hand and p.stack > 0:
                needed = max(0, to_call - p.bet)

                if p.is_human:
                    action, raise_amt = self.prompt_user(p, needed)
                else:
                    action, raise_amt = p.decide(needed, pot, None)

                if action == "fold":
                    p.in_hand = False
                    print(f"{p.name} folds")
                elif action in ("call", "check"):
                    p.stack -= needed
                    p.bet += needed
                    print(f"{p.name} {'checks' if needed == 0 else 'calls $'+str(needed)}")
                elif action == "raise":
                    minimum = self.BIG
                    raise_final = max(minimum, raise_amt)
                    p.stack -= needed + raise_final
                    p.bet += needed + raise_final
                    to_call = p.bet
                    acted = {pl: False for pl in self.players if pl.in_hand and pl.stack > 0}  # everyone must respond
                    print(f"{p.name} raises to ${to_call}")

                acted[p] = True

            idx = (idx + 1) % len(self.players)
            if all(acted.get(pl, True) or not pl.in_hand for pl in self.players) and all(not pl.in_hand or pl.bet == to_call for pl in self.players):
                break
        return to_call

    # ── Human input helper ────────────────────────────────────────────────────
    def prompt_user(self, p: Player, needed: int):
        while True:
            prompt = f"You have ${p.stack}. {'Call $'+str(needed) if needed else 'Check'} / Raise / Fold? (c/r/f): "
            choice = input(prompt).strip().lower()[:1]
            if choice == "c":
                return ("check" if needed == 0 else "call", 0)
            if choice == "f":
                return "fold", 0
            if choice == "r":
                max_raise = p.stack - needed
                if max_raise < self.BIG:
                    print("You don't have enough chips to raise – choose another action.")
                    continue
                try:
                    amt = int(input(f"Raise amount (min {self.BIG}, max {max_raise}): "))
                except ValueError:
                    print("Enter a number.")
                    continue
                if self.BIG <= amt <= max_raise:
                    return "raise", amt
                print("Invalid raise size.")
            else:
                print("Enter c, r, or f.")

# ─── Main entry point ─────────────────────────────────────────────────────────

def main():
    try:
        n = int(input("How many CPU opponents (2‑4)? "))
        if n not in (2, 3, 4):
            raise ValueError
    except ValueError:
        print("Please enter 2, 3, or 4.")
        sys.exit(1)

    game = Holdem(n)
    game.play()


if __name__ == "__main__":
    main()
