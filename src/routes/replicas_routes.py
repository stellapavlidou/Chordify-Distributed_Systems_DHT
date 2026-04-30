from flask import Blueprint, request, make_response
import json
import requests
from requests.adapters import HTTPAdapter

from node import *
from state import state 

replica_blueprint = Blueprint("replica_blueprint", __name__)

@replica_blueprint.route('/shiftReplicas',methods=['POST'])
def shift_replicas():
    keys_to_delete = set()
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=0))
    
    for (k,(key,value,replica_num)) in state.node.replicas.items():
        if replica_num == 1:
            
            fwd_resp = session.post("http://{}:{}/insertReplicas".format(state.node.next_node.ip,state.node.next_node.port),params={"key":key,"value":value,"replica_number":1})
            
            keys_to_delete.add(k)

    # Delete unnecessary keys
    for k in keys_to_delete:
        del state.node.replicas[k]

    return "Replicas of previous node shifted.", 200



@replica_blueprint.route('/queryReplicas')
def query_replicas():
    key_param = request.args.get("key")
    hashed_key, stored_value, replica_num = state.node.replicas[hash_key(key_param)]

    if not state.node.key == state.node.successor(key_param).key:

        payload = {
            "hash": hashed_key,
            "key": key_param,
            "value": stored_value,
            "replica_number": replica_num,
            "node_ip": state.node.ip,
            "node_port": state.node.port,
        }
        response = make_response(json.dumps(payload), 200)
        response.mimetype = "application/json"
    
        if replica_num == state.node.kfactor - 1:
            return response
        else:
                
            session = requests.Session()
            session.mount('http://', HTTPAdapter(max_retries=0))
            url = "http://{}:{}/queryReplicas".format(state.node.next_node.ip,state.node.next_node.port)
            fwd_resp = session.get(url,params={"key":key_param})

            if fwd_resp.status_code == 200:
                response = make_response(json.dumps(fwd_resp.json()), 200)
                response.mimetype = "application/json"
                return response
            elif fwd_resp.status_code == 204:
                return response
    else:
        return "Replica manager only have original data.", 204


@replica_blueprint.route('/insertReplicas',methods=['POST'])
def insert_replicas():
    key_param = request.args.get("key")
    value = request.args.get("value")
    replica_number = int(request.args.get("replica_number"))
    
    # Check if already have this key in data
    # Only edge case if kfactor >= number on nodes
    if not state.node.key == state.node.successor(key_param).key:

        # Update replica key
        state.node.add_replica(key_param, value, replica_number)

        if replica_number < state.node.kfactor - 1:
            session = requests.Session()
            session.mount('http://', HTTPAdapter(max_retries=0))
            url = "http://{}:{}/insertReplicas".format(state.node.next_node.ip,state.node.next_node.port)
            fwd_resp = session.post(url,params={"key":key_param,"value":value,"replica_number":replica_number + 1})
            
            return fwd_resp.text

    return "Key {} & its replicas added successfully".format(key_param), 200

@replica_blueprint.route('/fixReplicas',methods=['PUT'])
def fix_replicas():
    initial_node = int(request.args.get("keynode"))
    hop = int(request.args.get("hop"))

    json_body = request.get_json()
    initial_node_keys = set(json.loads(json_body)["keys"])
    
    # Only edge case if kfactor >= number on nodes
    if not state.node.key == initial_node:

        # Fix your replicas
        expired_replicas = set()
        for (k,(key, value, replica_number)) in state.node.replicas.items():
            if replica_number > hop or (replica_number == hop and not k in initial_node_keys):
                if replica_number < state.node.kfactor - 1:
                    state.node.add_replica(key,value,replica_number + 1)
                else:
                    expired_replicas.add(k)
        
        for k in expired_replicas:
            del state.node.replicas[k]

        if hop < state.node.kfactor - 1:
            session = requests.Session()
            session.mount('http://', HTTPAdapter(max_retries=0))
            url = "http://{}:{}/fixReplicas".format(state.node.next_node.ip,state.node.next_node.port)
            fwd_resp = session.put(url,params={"keynode":initial_node,"hop": hop + 1},json=json_body)
            
            return fwd_resp.text

    return "Replication number updated.", 200

@replica_blueprint.route('/initfixReplicas')
def init_fix_replicas():
    if not state.node.next_node == None:

        # Send a list of your primary keys
        # , that weren't send to new node
        keys_payload = {"keys":list(state.node.data.keys())}

        session = requests.Session()
        session.mount('http://', HTTPAdapter(max_retries=0))
        url = "http://{}:{}/fixReplicas".format(state.node.next_node.ip,state.node.next_node.port)
        session.put(url,params={"keynode":state.node.key,"hop": 1},json=json.dumps(keys_payload))

        return "Fix Replicas Operation ended.", 200
    else:
        return "No need for Fix Replicas Sequence", 200

@replica_blueprint.route('/generateReplicas')
def generate_replicas():
    # Read set of existing keys
    existing_keys = set(json.loads(request.get_json())["existing"])
    # Check primary keys
    new_replicas = {}
    for (k,(key,value)) in state.node.data.items():
        if k not in existing_keys:
            new_replicas[k] = (key,value,1)
    # Check replicas
    for (k,(key,value,replica_number)) in state.node.replicas.items():
        if replica_number < state.node.kfactor - 1 and k not in existing_keys:
            new_replicas[k] = (key,value,replica_number + 1)
    
    result_payload = {"keys":[{"key":v[0],"value":v[1],"replica_number":v[2]} for (k,v) in new_replicas.items()]}
    response = make_response(json.dumps(result_payload), 200)
    response.mimetype = "application/json"
    return response


@replica_blueprint.route('/deleteReplicas',methods=['DELETE'])
def delete_replicas():
    key_param = request.args.get("key")
    replica_number = int(request.args.get("replica_number"))
    

    # Edge case for kfactor >= number of nodes
    if not state.node.key == state.node.successor(key_param).key:
        
        # Delete replica key
        del state.node.replicas[hash_key(key_param)]

        if replica_number < state.node.kfactor - 1:
                
            session = requests.Session()
            session.mount('http://', HTTPAdapter(max_retries=0))
            url = "http://{}:{}/deleteReplicas".format(state.node.next_node.ip,state.node.next_node.port)
            fwd_resp = session.delete(url,params={"key":key_param,"replica_number":replica_number + 1})
            
            return fwd_resp.text, fwd_resp.status_code
    
    return "Key '{}' & its replicas deleted.".format(key_param), 200
