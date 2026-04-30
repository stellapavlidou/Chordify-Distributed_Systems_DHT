from flask import Blueprint, request, make_response
import json
import requests
from requests.adapters import HTTPAdapter

from node import *
from state import state

managemnt_blueprint = Blueprint("managemnt_bluerint", __name__)

@managemnt_blueprint.route('/join', methods=['PUT'])
def join():
    bootstrap_ip = request.args.get("ip")
    bootstrap_port = int(request.args.get("port"))

    if not state.node is None:
        return "You're already part of chord.",403

    if state.ip == bootstrap_ip and state.port == bootstrap_port:
        state.node = BootstrapNode(state.ip, state.port, state.kfactor, state.consistency)
        return "New chord created.", 200

    state.node = Node(state.ip, state.port, (bootstrap_ip, bootstrap_port), state.kfactor, state.consistency)

    # Communicate with bootstrap node
    url = "http://{}:{}/addNode".format(bootstrap_ip,bootstrap_port)
    join_resp = requests.put(url, params={"ip":state.node.ip,"port":state.node.port})
    
    if join_resp.status_code == 200:

        resp_data = join_resp.json()
        state.node.previous_node = ReferenceNode(resp_data["previous"]["ip"],int(resp_data["previous"]["port"]))
        state.node.next_node = ReferenceNode(resp_data["next"]["ip"],int(resp_data["next"]["port"]))
        
        # Inform neighboors
        # Receive keys from next
        url = "http://{}:{}/transferKeys".format(state.node.next_node.ip,state.node.next_node.port)
        transfer_resp = requests.get(url, params={"keynode":state.node.key})

        # Download Primary Keys
        transfer_data = transfer_resp.json()
        state.node.data = {d["key_hash"]:(d["key"],d["value"]) for d in transfer_data["keys"]}

        if state.node.kfactor > 1:

            if state.node.consistency_type == "chain-replication" or state.node.consistency_type == "eventually":
                
                state.node.replicas = {d["key_hash"]:(d["key"],d["value"],d["replica_number"]) for d in transfer_data["replicas"]}
                # Initiate fix replicas operation
                session = requests.Session()
                session.mount('http://', HTTPAdapter(max_retries=0))
                url = "http://{}:{}/initfixReplicas".format(state.node.next_node.ip,state.node.next_node.port)
                session.get(url)

        # Inform previous
        url = "http://{}:{}/changeNext".format(state.node.previous_node.ip,state.node.previous_node.port)
        prev_resp = requests.put(url, params={"ip":state.node.ip,"port":state.node.port})
        
        # Inform next
        url = "http://{}:{}/changePrevious".format(state.node.next_node.ip,state.node.next_node.port)
        next_resp = requests.put(url, params={"ip":state.node.ip,"port":state.node.port})

        if state.node.kfactor == 1:
            # Tell next to delete unnecessary keys
            url = "http://{}:{}/deleteKeys".format(state.node.next_node.ip,state.node.next_node.port)
            del_resp = requests.delete(url, params={"keynode":state.node.key})

        # Edge case:
        elif state.node.kfactor > 1:
            
            existing_payload = {"existing":list(state.node.replicas.keys()) + list(state.node.data.keys())}
            url = "http://{}:{}/generateReplicas".format(state.node.previous_node.ip,state.node.previous_node.port)
            gen_resp = requests.get(url,json=json.dumps(existing_payload))

            generated_keys = gen_resp.json()["keys"]

            for d in generated_keys:
                state.node.add_replica(d["key"],d["value"],d["replica_number"])
        
        return "New node added successfully!", 200

    else:
        return join_resp.text, join_resp.status_code

@managemnt_blueprint.route('/changeNext',methods=['PUT'])
def change_next():
    new_ip = request.args.get("ip")
    new_port = int(request.args.get("port"))
    if new_ip == state.node.ip and state.node.port == new_port:
        state.node.next_node = None
    else:
        state.node.next_node = ReferenceNode(new_ip,new_port)
    return "Changed next node.", 200

@managemnt_blueprint.route('/changePrevious',methods=['PUT'])
def change_previous():
    new_ip = request.args.get("ip")
    new_port = int(request.args.get("port"))
    if new_ip == state.node.ip and state.node.port == new_port:
        state.node.previous_node = None
    else:
        state.node.previous_node = ReferenceNode(new_ip,new_port)
    return "Changed previous node.", 200

@managemnt_blueprint.route('/addNode', methods=['PUT'])
def add_node():
    if not state.node.is_bootstrap():
        return "I'm not the bootstrap server. Please contact {}:{}".format(state.node.bnode.ip,state.node.bnode.port), 301
    
    node_ip = request.args.get("ip")
    node_port = int(request.args.get("port"))
    keynode = state.node.add_node(node_ip, node_port)
    if keynode == -1:
        return "Node is already inside chord.", 405
    
    prev_node, next_node = state.node.find_neighboors(keynode)
    neighbor_data = {"previous":{"ip":prev_node[0],"port":prev_node[1]}, "next":{"ip":next_node[0],"port":next_node[1]}}
    
    response = make_response(json.dumps(neighbor_data), 200)
    response.mimetype = "application/json"
    return response
   

@managemnt_blueprint.route('/depart', methods=['DELETE'])
def depart():
    if state.node is None:
        return "You have to join first.", 403

    if state.node.is_bootstrap():
        return "Bootstrap node is not allowed to depart!", 403
  
    # Send keys to next node
    if not state.node.data == {}:
        keys_list = [{"key_hash":k,"key":v[0],"value":v[1]} for (k,v) in state.node.data.items()]
        keys_payload = {"keys":keys_list}
        send_resp = requests.post("http://{}:{}/send".format(state.node.next_node.ip,state.node.next_node.port), json=json.dumps(keys_payload))

        # In case of replication, my replicas sould shift
        if state.node.kfactor > 1:
            
            if state.node.consistency_type == "chain-replication" or state.node.consistency_type == "eventually":
                
                session = requests.Session()
                session.mount('http://', HTTPAdapter(max_retries=0))
                shift_resp = session.post("http://{}:{}/shiftReplicas".format(state.node.next_node.ip,state.node.next_node.port))

    # Send replicas
    if not state.node.replicas == {}:

        if state.node.consistency_type == "chain-replication" or state.node.consistency_type == "eventually":            
            
            session = requests.Session()
            session.mount('http://', HTTPAdapter(max_retries=0))
                    
            for (k,v) in state.node.replicas.items():
                replica_resp = session.post("http://{}:{}/insertReplicas".format(state.node.next_node.ip,state.node.next_node.port),params={"key":v[0],"value":v[1],"replica_number":v[2]})

    # Communicate with bootstrap node
    url = "http://{}:{}/removeNode".format(state.node.bnode.ip,state.node.bnode.port)
    remove_resp = requests.delete(url, params={"keynode":state.node.key})
    
    # Inform neighboors
    # Inform Previous
    url = "http://{}:{}/changeNext".format(state.node.previous_node.ip,state.node.previous_node.port)
    requests.put(url, params={"ip":state.node.next_node.ip,"port":state.node.next_node.port})
    
    # Inform Next
    url = "http://{}:{}/changePrevious".format(state.node.next_node.ip,state.node.next_node.port)
    requests.put(url, params={"ip":state.node.previous_node.ip,"port":state.node.previous_node.port})
    
    state.node = None
    
    return remove_resp.text


@managemnt_blueprint.route('/kickout', methods=['DELETE'])
def kickout():
    if state.node.is_bootstrap():
        return "Bootstrap node is not allowed to be excluded!", 200

    state.node = None
    return "Node object deleted!", 200

@managemnt_blueprint.route('/removeNode', methods=['DELETE'])
def remove_node():
    if not state.node.is_bootstrap():
        return "I'm not the bootstrap server. Please contact {}:{}".format(state.node.bnode.ip,state.node.bnode.port), 301
    
    keynode = int(request.args.get("keynode"))
    if keynode == state.node.key:
        return "Bootstrap node is not allowed to depart!"
    
    result = state.node.delete_node(keynode)
    if result == -1:
        return "Node is not part of chord!", 403
    else:
        return "Node deleted succesfully!", 200

