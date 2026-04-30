#!/usr/bin/env python
from flask import Flask
import logging
import socket
import sys

from state import state
from routes.data_routes import data_blueprint
from routes.node_management_routes import managemnt_blueprint
from routes.system_routes import system_blueprint
from routes.replicas_routes import replica_blueprint

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.disabled = True

app.register_blueprint(data_blueprint)
app.register_blueprint(managemnt_blueprint)
app.register_blueprint(replica_blueprint)
app.register_blueprint(system_blueprint)

if __name__ == "__main__":

    if not len(sys.argv) == 4:
        print("Please provide available port number, replication factor & consistency type")
        exit()

    ip = socket.gethostbyname(socket.gethostname())
    port = int(sys.argv[1])
    kfactor = int(sys.argv[2])
    consistency = sys.argv[3]

    state.ip = ip
    state.port = port
    state.kfactor = kfactor
    state.consistency = consistency
    state.node = None

    try:
        app.run(host=ip, port=port)
    except socket.error:
        print("Port {} is not available".format(sys.argv[1]))
        exit()

