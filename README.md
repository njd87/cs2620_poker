# How to Start
Python version required: >= 3.11

First, run:

```console
python setup.py
```

Run all 5 servers in 5 terminals:

```console
python server.py 0
```

```console
python server.py 1
```

```console
python server.py 2
```

```console
python server.py 3
```

```console
python server.py 4
```

Next, run the 2 server lobbies in the 2 terminals:

```console
python server_lobby.py 0
```

```console
python server_lobby.py 1
```

The indices correspond to the hosts and ports in config.

Running a client is simple:

```console
python client.py
``` 

It will automatically connect and find new leader whenever needed. Feel free to change host and port numbers.

# How to Use

Interact via tkinter window to enter username, login/register. Then, select a lobby to join. If a lobby is available, it will prompt you to join that lobby (requirement of at least 100 moolah to join)

Games will not begin until there are at least 2 players and they all vote to play.
If a player leaves, game will continue without missing player.
Money updated after game is complete. 5 rounds per game.

Texas holdem rules: https://bicyclecards.com/how-to-play/texas-holdem-poker
5 card draw rules: https://www.contrib.andrew.cmu.edu/~gc00/reviews/pokerrules#:~:text=Five%20card%20draw%20is%20one,cards%20as%20he%2Fshe%20discarded.