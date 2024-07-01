import sys

from hat.mariner.server.main import main


if __name__ == '__main__':
    sys.argv[0] = 'hat-mariner-server'
    sys.exit(main())
