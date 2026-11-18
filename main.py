import sys

sys.dont_write_bytecode = True

from modules.app import run


if __name__ == "__main__":
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        import os
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    run()
