from flask import Blueprint, request, make_response
import json
import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor

from node import *
from state import state 
from services.node_network import *

data_blueprint= Blueprint("data_blueprint", __name__)

executor = ThreadPoolExecutor(max_workers=10)

def data_transfer(method, url, params, payload):
    try:
        if method == "POST":
            requests.post(url, params=params, json=payload, timeout=5)
        elif method == "DELETE":
            requests.delete(url, params=params, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"Async operation failed: {e}")
        
@data_blueprint.route('/query')
def query():
    key_param = request.args.get("key")

    if state.node is None:
        return "You have to join first.", 403
    
    if key_param == "*":      
        result_list = [{
                        "node":{"hash":state.node.key, "ip":state.node.ip, "port":state.node.port}, 
                        "keys":[{"hash":k, "key":v[0], "value":v[1]} for k,v in state.node.data.items()], 
                        "replicas":[{"hash":k, "key":v[0], "value":v[1],"replica_number":v[2]} for k,v in state.node.replicas.items()],
                    }]

        response = make_response(json.dumps(result_list), 200)
        response.mimetype = "application/json"
        return response

    key = hash_key(key_param)
    successor = state.node.successor(key_param)
    
    if successor.key == state.node.key:
        
        if key not in state.node.data:
            return "Key not found.",404
        
        payload = {
                "hash": key,
                "key": state.node.data[key][0],
                "value": state.node.data[key][1],
                "replica_number": "original",
                "node_ip": state.node.ip,
                "node_port": state.node.port,
            }
        query_response = make_response(json.dumps(payload), 200)
        query_response.mimetype = "application/json"
        
        if state.node.kfactor == 1 or state.node.consistency_type == "eventually":
            return query_response

        elif state.node.consistency_type == "chain-replication":    
            return forward_query(state.node.next_node.ip,state.node.next_node.port, key_param)        

    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=0))

    if state.node.kfactor > 1 and key in state.node.replicas:

        payload = {
            "hash": key,
            "key": state.node.replicas[key][0],
            "value": state.node.replicas[key][1],
            "replica_number": state.node.replicas[key][2],
            "node_ip": state.node.ip,
            "node_port": state.node.port,
        }

        query_response = make_response(json.dumps(payload), 200)
        query_response.mimetype = "application/json"
        
        if state.node.consistency_type == "eventually":          
            return query_response

        elif state.node.consistency_type == "chain-replication":            
            if state.node.replicas[key][2] == state.node.kfactor - 1 or state.node.next_node.key == successor.key: 
                return query_response
            else:
                return forward_query(state.node.next_node.ip,state.node.next_node.port, key_param)
            
    # Send key to successor
    return forward_query(successor.ip, successor.port , key_param)


@data_blueprint.route('/nextNode')
def next_node():
    if state.node == None or state.node.next_node == None:
        response = make_response(json.dumps({}), 204)
    else:
        response = make_response(json.dumps({"ip":state.node.next_node.ip,"port":state.node.next_node.port}), 200)

    response.mimetype = "application/json"
    return response

@data_blueprint.route('/queryAll')
def query_all():
    if state.node is None:
        return "You have to join first.", 403

    result_list = [{
                    "node":{"hash":state.node.key,"ip":state.node.ip,"port":state.node.port}, 
                    "keys":[{"hash":k,"key":v[0], "value":v[1]} for k,v in state.node.data.items()], 
                    "replicas":[{"hash":k,"key":v[0], "value":v[1],"replica_number":v[2]} for k,v in state.node.replicas.items()],
                }]
    
    current_next = state.node.next_node

    if not current_next == None:

        while not current_next.key == state.node.key:
            # Find next node for query
            url = "http://{}:{}/nextNode".format(current_next.ip,current_next.port)
            next_resp = requests.get(url)
            
            # Receive keys for next node
            url = "http://{}:{}/query".format(current_next.ip,current_next.port)
            keys_resp = requests.get(url, params={"key":"*"})

            # Update result_list
            if keys_resp.status_code == 200:
                result_list = result_list + keys_resp.json()

            # Update next node
            resp_data = next_resp.json()
            current_next = ReferenceNode(resp_data["ip"],resp_data["port"])        

    response = make_response(json.dumps(result_list), 200)
    response.mimetype = "application/json"

    return response

@data_blueprint.route('/insert',methods=['POST'])
def insert():
    key_param = request.args.get("key")
    value = request.args.get("value")

    if state.node is None:
        return "You have to join first.", 403
    
    successor = state.node.successor(key_param)

    if successor.key == state.node.key:
        
        # Add key here
        key = state.node.add_key(key_param,value)

        payload = {
            "hash": key,
            "key": key_param,
            "value": value,
            "node_ip": state.node.ip,
            "node_port": state.node.port,
        }
        insert_resp = make_response(json.dumps(payload), 200)
        insert_resp.mimetype = "application/json"


        if state.node.kfactor > 1:

            url = "http://{}:{}/insertReplicas".format(state.node.next_node.ip,state.node.next_node.port)
            params = {"key":key_param,"value":value,"replica_number":1}

            if state.node.consistency_type == "chain-replication":
                
                session = requests.Session()
                session.mount('http://', HTTPAdapter(max_retries=0))
                fwd_resp = session.post(url,params=params)
            
            elif state.node.consistency_type == "eventually":          
                executor.submit(data_transfer, "POST", url, params, payload)
                return "Write initiated (eventual)", 202
            
        return insert_resp
    
    else:
        
        # Send key to successor
        session = requests.Session()
        session.mount('http://', HTTPAdapter(max_retries=0))
        url = "http://{}:{}/insert".format(successor.ip,successor.port)
        fwd_resp = session.post(url,params={"key":key_param,"value":value})
        
        if fwd_resp.status_code == 200:
            response = make_response(json.dumps(fwd_resp.json()), 200)
            response.mimetype = "application/json"
            return response

        else:
            return fwd_resp.text, fwd_resp.status_code

@data_blueprint.route('/send',methods=['POST'])
def send():
    incoming_keys = json.loads(request.get_json())["keys"]
    for d in incoming_keys:
        state.node.data[d["key_hash"]] = (d["key"],d["value"])
    return "Keys transfered!", 200

@data_blueprint.route('/transferKeys')
def transfer_keys():
    keynode = int(request.args.get("keynode"))

    if state.node.kfactor == 1:
        
        result_list = [{"key_hash":k,"key":v[0],"value":v[1]} for (k,v) in state.node.data.items() if k <= keynode or k > state.node.key]
        payload = {"keys":result_list}
        
    elif state.node.consistency_type == "chain-replication" or state.node.consistency_type == "eventually":
        
        primary_data = {k:v for (k,v) in state.node.data.items() if k <= keynode or k > state.node.key}
        replica_entries = [{"key_hash":k,"key":v[0],"value":v[1],"replica_number":v[2]} for (k,v) in state.node.replicas.items()]

        # Increase replication number on 
        # your own replication dictionairy
        expired_replicas = set()
        
        for (k,(key,value,replica_number)) in state.node.replicas.items():
            if replica_number < state.node.kfactor - 1:
                state.node.add_replica(key, value, replica_number + 1)
            else:
                expired_replicas.add(k)

        for k in expired_replicas:
            del state.node.replicas[k]

        # Each primary key of node, that will be send
        # to new node, must be added as a replica
        for (k,(key,value)) in primary_data.items():
            state.node.add_replica(key,value,1)

        # Uneccessary keys must be now deleted
        for k in primary_data.keys():
            del state.node.data[k]
        
        # Format json output
        primary_data = [{"key_hash":k,"key":v[0],"value":v[1]} for (k,v) in primary_data.items()]
        payload = {"keys":primary_data,"replicas":replica_entries}

    response = make_response(json.dumps(payload), 200)
    response.mimetype = "application/json"
    return response

@data_blueprint.route('/deleteKeys',methods=['DELETE'])
def delete_keys():
    keynode = request.args.get("keynode")

    if not keynode == None:
        keynode = int(keynode)
        state.node.data = {k:v for (k,v) in state.node.data.items() if not(k <= keynode or k > state.node.key)}

    return "Keys deleted.", 200

@data_blueprint.route('/delete', methods=['DELETE'])
def delete():
    key_param = request.args.get("key")
    key = hash_key(key_param)

    if state.node is None:
        return "You have to join first.", 403
    
    successor = state.node.successor(key_param)
    if successor.key == state.node.key:
        if key in state.node.data:

            payload = {
                "hash": key,
                "key": state.node.data[key][0],
                "value": state.node.data[key][1],
                "node_ip": state.node.ip,
                "node_port": state.node.port,
            }
            delete_resp = make_response(json.dumps(payload), 200)
            delete_resp.mimetype = "application/json"
        
            del state.node.data[key]

            if state.node.kfactor == 1:
                return delete_resp
            else:

                url = "http://{}:{}/deleteReplicas".format(state.node.next_node.ip,state.node.next_node.port)
                params = {"key":key_param,"replica_number":1}

                if state.node.consistency_type == "chain-replication":
                    
                    session = requests.Session()
                    session.mount('http://', HTTPAdapter(max_retries=0))
                    fwd_resp = session.delete(url,params=params)
                    
                    if fwd_resp.status_code == 200:
                        return delete_resp
                    else:
                        return fwd_resp.text, fwd_resp.status_code

                elif state.node.consistency_type == "eventually":
                    executor.submit(data_transfer, "DELETE", url, params, payload)
                    return "DELETE initiated (eventual)", 202
        else:
            return "Key not found.",404
    else:
        # Send key to successor
        session = requests.Session()
        session.mount('http://', HTTPAdapter(max_retries=0))
        url = "http://{}:{}/delete".format(successor.ip,successor.port)
        fwd_resp = session.delete(url,params={"key":key_param})
        if fwd_resp.status_code == 200:
            response = make_response(json.dumps(fwd_resp.json()), 200)
            response.mimetype = "application/json"
            return response
        else:
            return fwd_resp.text, fwd_resp.status_code
