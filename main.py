import socket
import sys
import traceback
import os


def main():
    try:
        username = socket.gethostname()

        from ui import MainWindow
        app = MainWindow(username)
        app.run()
    except Exception:
        log_path = os.path.join(os.path.dirname(__file__) or ".", "lanchat_error.log")
        with open(log_path, "w") as f:
            traceback.print_exc(file=f)
        raise


if __name__ == "__main__":
    main()
