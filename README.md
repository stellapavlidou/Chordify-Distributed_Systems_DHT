# Chordify: DHT system


## Installation of dependencies  

```
cd src/
pip install -r ./requirements.txt
```

## Deployment
```
cd /src
# No replication of data
./chord.py
# Replication of data with 2 copies of each key-value pair & chain-replication
./chord.py 2 chain-replication
# Replication of data wit 5 copies of each key-value pair & eventually consistency
./chord.py 5 eventually
```

## CLI Commands
```
chord-cli@ntua$ help
Usage:   COMMAND [OPTIONS] [ARGS]

Commands:
  delete   Deletes the specified <key>.
  depart   Makes current node to depart.
  exit     Makes current node to depart & exits from shell.
  help     Prints this message and exits.
  info     Displays info for current node.
  insert   Inserts the pair (<key>, <value>).
  join     Inserts a new node.
  overlay  Displays current network topology.
  query    Finds the value of <key>.
```