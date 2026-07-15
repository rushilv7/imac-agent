#!/usr/bin/env python3

import logging
import os
import socket
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

hostname = socket.gethostname()
pid = os.getpid()

logging.info("imac-demo starting: hostname=%s pid=%s", hostname, pid)

while True:
    logging.info("heartbeat: imac-demo is healthy")
    time.sleep(30)
