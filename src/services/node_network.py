"""
network.py

Handles inter-node HTTP communication for the Chord system.
Contains forwarding and request helper utilities.
"""
import requests
from flask import jsonify


def forward_query(ip: str, port: int, key_value: str):
    """
    Forwards a query request to another Chord node.

    This function sends an HTTP GET request to the /query endpoint
    of the target node and returns the response exactly as received.

    Parameters
    ----------
    ip : str
        The IP address of the target node.

    port : int
        The port number of the target node.

    key_value : str
        The key (not hashed) that we want to query.

    Returns
    -------
    tuple
        A Flask-compatible response tuple:
        - (json_response, 200) if successful
        - (error_text, status_code) if the remote node returned an error
        - ("Node unreachable.", 503) if the request failed
    """

    try:
        url = f"http://{ip}:{port}/query"

        response = requests.get(
            url,
            params={"key": key_value},
            timeout=2  
        )

        if response.status_code == 200:
            return jsonify(response.json()), 200

        return response.text, response.status_code

    except requests.RequestException:
        return "Node unreachable.", 503