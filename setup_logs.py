import os
import glob

def delete_files_in_directory(directory):
    if not os.path.isdir(directory):
        print(f"Directory not found: {directory}")
        return
    files = glob.glob(os.path.join(directory, '*'))
    for file in files:
        if os.path.isfile(file):
            os.remove(file)
            print(f"Deleted: {file}")

if __name__ == "__main__":
    delete_files_in_directory('logs/lobby_logs')
    delete_files_in_directory('logs/server_logs')