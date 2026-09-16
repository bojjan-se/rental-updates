#!/usr/bin/env python3
import argparse
import sys

from src.scheduler import main, send_test_notification

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Rental listings monitor")
    parser.add_argument('--config', default='config.yaml', help='path to config file (default: config.yaml)')
    parser.add_argument('--test-notify', action='store_true',
                        help='send a test notification through every enabled channel, then exit')
    args = parser.parse_args()

    if args.test_notify:
        sys.exit(0 if send_test_notification(args.config) else 1)
    main(args.config)
