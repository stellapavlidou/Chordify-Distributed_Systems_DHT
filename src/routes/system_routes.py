from flask import Blueprint, make_response
import json
import requests
import threading
import os
import signal
from state import state 

system_blueprint = Blueprint("system_blueprint", __name__)

def shutdown_server():
    print("Shutting down Chordify server...")
    os.kill(os.getpid(), signal.SIGINT)

def trigger_delayed_shutdown(delay=0.5):
    shutdown_thread = threading.Timer(delay, shutdown_server)
    shutdown_thread.start()


@system_blueprint.route('/')
def health_check():
    return "\nServer is up and running in {}:{} !".format(state.ip, state.port)

@system_blueprint.route('/overlay')
def overlay():

    if state.node is None:
        return "You have to join first.", 403
    
    if state.node.is_bootstrap():
        overlay_data = {"nodes":[{"node_key":key,"ip":ip_port[0],"port":ip_port[1]} for key,ip_port in state.node.nodes.items()]}
        response = make_response(json.dumps(overlay_data), 200)
        response.mimetype = "application/json"
        return response

    url = "http://{}:{}/overlay".format(state.node.bnode.ip,state.node.bnode.port)
    overlay_resp = requests.get(url)
    if overlay_resp.status_code == 200:
        response = make_response(json.dumps(overlay_resp.json()), 200)
        response.mimetype = "application/json"
        return response

    url = "http://{}:{}/overlay".format(state.node.bnode.ip,state.node.bnode.port)
    r = requests.get(url)
    if r.status_code == 200:
        response = make_response(json.dumps(r.json()), 200)
        response.mimetype = "application/json"
        return response
    else:
        return overlay_resp.text, overlay_resp.status_code

@system_blueprint.route('/info')
def info():
    if state.node is None:
        return "You have to join first.", 403

    node_info = {
        "keys": [{"key_hash":k,"key":v[0],"value":v[1]} for (k,v) in state.node.data.items()],
        "replicas": [{"key_hash":k,"key":v[0],"value":v[1],"replica_num":v[2]} for (k,v) in state.node.replicas.items()],
        "previous": {},
        "next": {},
    }
    if state.node.previous_node != None:
        node_info["previous"] = {
            "hash": state.node.previous_node.key,
            "ip": state.node.previous_node.ip,
            "port": state.node.previous_node.port,
        }
        
    if state.node.next_node != None:
        node_info["next"] = { 
            "hash": state.node.next_node.key,
            "ip": state.node.next_node.ip,
            "port": state.node.next_node.port,
        }

    response = make_response(json.dumps(node_info), 200)
    response.mimetype = "application/json"
    return response

@system_blueprint.route('/shutdown', methods=['POST'])
def shutdown():
    """
    Shuts down currents node and forwards the request to the next node.
    """
    if state.node is None:
        trigger_delayed_shutdown()
        return "Server was not initialized. Shutting down...", 200

    try:
        if state.node.is_bootstrap():
            if state.node.number_of_nodes > 1:
                for node_id, addr in state.node.nodes.items():
                    target_url = f"http://{addr[0]}:{addr[1]}/kickout"
                    try:
                        requests.delete(target_url, timeout=2)
                    except requests.exceptions.RequestException:
                        print(f"Failed to notify node {node_id} at {target_url}")
        else:
            depart_url = f"http://{state.node.ip}:{state.node.port}/depart"
            try:
                requests.delete(depart_url, timeout=2)
            except requests.exceptions.RequestException:
                print("Failed to send depart notification.")

    except Exception as err:
        print(f"Error during network cleanup: {err}")

    trigger_delayed_shutdown(delay=0.5)
    
    return "Chord node cleanup initiated. Server shutting down..."
   
