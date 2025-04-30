import os
import sqlite3

def reset_database(files) -> None:
    """
    Reset the database by deleting the file if it exists.
    """

    # check to make sure the "data" directory exists
    # database stored here
    os.makedirs("data/r1", exist_ok=True)
    os.makedirs("data/r2", exist_ok=True)
    os.makedirs("data/r3", exist_ok=True)
    os.makedirs("data/r4", exist_ok=True)
    os.makedirs("data/r5", exist_ok=True)

    # delete everything in the data directory, including subdirectories
    for file in files:
        if os.path.exists(file):
            os.remove(file)


def structure_tables(data_path="data/messenger.db") -> None:
    """
    Create the tables for the database.
    """

    with sqlite3.connect(data_path) as conn:
        cursor = conn.cursor()

        # set up users table in messenger.db file
        cursor.execute(
            """
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                passhash TEXT NOT NULL,
                moolah INTEGER DEFAULT 500
            );
            """
        )

        # set up games table in messenger.db file
        cursor.execute(
            """
            CREATE TABLE game_history (
                game_id INTEGER PRIMARY KEY,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER NOT NULL,
                player3_id INTEGER NOT NULL,
                player4_id INTEGER NOT NULL,
                winner_id INTEGER NOT NULL,
                game_date DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """
        )
        conn.commit()
        print(f"Created users table.")
        print(f"Created game table.")


def print_db(data_path="data/messenger.db") -> None:
    """
    Print the contents of the database.
    """

    with sqlite3.connect(data_path) as conn:
        cursor = conn.cursor()

        # print users table
        cursor.execute("SELECT * FROM users")
        print("Users Table")
        for row in cursor.fetchall():
            print(row)

        # print games table
        cursor.execute("SELECT * FROM game_history")
        print("Game History Table")
        for row in cursor.fetchall():
            print(row)

        # close the connection
        conn.close()

if __name__ == "__main__":
    reset_database([
        "data/r1/poker.db",
        "data/r2/poker.db",
        "data/r3/poker.db",
        "data/r4/poker.db",
        "data/r5/poker.db"
    ])

    structure_tables("data/r1/poker.db")
    structure_tables("data/r2/poker.db")
    structure_tables("data/r3/poker.db")
    structure_tables("data/r4/poker.db")
    structure_tables("data/r5/poker.db")

    # print_db("data/r1/messenger.db")
    # print_db("data/r2/messenger.db")
    # print_db("data/r3/messenger.db")
    # print_db("data/r4/messenger.db")
    # print_db("data/r5/messenger.db")