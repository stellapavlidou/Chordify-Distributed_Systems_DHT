import subprocess
import time
import requests
import threading
import os
from pathlib import Path

# ---------------- CONFIG ----------------
BASE_PORT = 5000
NUM_NODES = 10
K_FACTORS = [1, 3, 5]
CONSISTENCIES = ["chain-replication","eventually"]
IP = "192.168.2.8" 
INSERT_FOLDER = Path("./insert_files")
REQUESTS_FILE = "requests.txt"

def start_node_server(port, k, consistency):
    env = os.environ.copy()
    # Προσαρμογή ανάλογα με το πώς δέχεται ο server.py τα arguments
    return subprocess.Popen(
        ["python", "../src/server.py", str(port), str(k), consistency],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def send_depart_to_all():
    for i in range(NUM_NODES):
        port = BASE_PORT + NUM_NODES - i -1
        try:
            requests.delete(f"http://{IP}:{port}/depart",params={"ip": IP, "port": port}, timeout=7)
            time.sleep(1)
        except Exception as e:
            print(f"Node {NUM_NODES -1 -i} failed to depart:\n{e}")


def experiment_1_and_2(k, consistency):
    processes = []
    print(f"\n>>> Testing K={k}, Consistency={consistency}")
    
    # 1. Start Nodes
    for i in range(NUM_NODES):
        p = start_node_server(BASE_PORT + i, k, consistency)
        processes.append(p)
    
    time.sleep(2) # Wait for Flask to bind

    # 2. Join Nodes sequentially
    bootstrap_url = {"ip": IP, "port": BASE_PORT}
    for i in range(NUM_NODES):
        port = BASE_PORT + i
        try:
            requests.put(f"http://{IP}:{port}/join", params=bootstrap_url, timeout=5)

            time.sleep(2) 
        except Exception as e:
            print(f"Node {i} failed to join: {e}")

    print(f"All nodes joined!")

    # --- 1. INSERT PHASE ---
    insert_threads = []
    insert_lock = threading.Lock()
    total_inserts = 0
    start_insert = time.time()
    
    def local_insert_worker(node_id):
        nonlocal total_inserts
        file_path = INSERT_FOLDER / f"insert_{node_id}.txt"
        if not file_path.exists(): return
        
        with requests.Session() as session:
            with open(file_path, 'r') as f:
                for line in f:
                    key = line.strip()
                    try:
                        r = session.post(f"http://{IP}:{BASE_PORT + node_id}/insert", 
                                      params={"key": key}, timeout=5)
                        if r.status_code == 200 or r.status_code == 202:
                            with insert_lock:
                                total_inserts += 1
                        else:
                            print(r.status_code)
                    except Exception as e:
                        print(e , r.status_code)
                        pass

    for i in range(NUM_NODES):
        t = threading.Thread(target=local_insert_worker, args=(i,))
        insert_threads.append(t)
        t.start()
        time.sleep(0.05)

    for t in insert_threads:
        t.join()

    insert_time = time.time() - start_insert
    write_throughput = total_inserts / insert_time
    print(f"Insert Time: {insert_time:.2f}s | Write Throughput: {write_throughput:.2f} inserts/sec")

    with open("results_experiment1.txt", "a", encoding="utf-8") as f:
        f.write(f"K={k}, Consistency={consistency} | Total Insert Time: {insert_time:.2f}s | Write Throughput: {write_throughput:.2f} inserts/sec\n")

    time.sleep(2)
    # --- 2. QUERY PHASE ---
    query_threads = []
    query_lock = threading.Lock()
    total_queries = 0
    start_query = time.time()

    def query_worker(node_id):
        nonlocal total_queries
        file_path = Path("./query_files") / f"query_{node_id}.txt"
        if not file_path.exists(): return
        
        with requests.Session() as session:
            with open(file_path, 'r') as f:
                for line in f:
                    key = line.strip()
                    try:
                        r = session.get(f"http://{IP}:{BASE_PORT + node_id}/query", 
                                         params={"key": key}, timeout=5)
                        if r.status_code == 200:
                            with query_lock:
                                total_queries += 1
                        else:
                            print(r.status_code, r.text, key)
                            break
                    except Exception as e:
                        print(e , r.status_code)
                        pass

    for i in range(NUM_NODES):
        t = threading.Thread(target=query_worker, args=(i,))
        query_threads.append(t)
        t.start()
        time.sleep(0.05)

    for t in query_threads:
        t.join()

    duration_query = time.time() - start_query
    throughput = total_queries / duration_query if duration_query > 0 else 0
    print(f"Query time: {duration_query:.2f}s | Read Throughput: {throughput:.2f} queries/sec")

    with open("results_experiment2.txt", "a", encoding="utf-8") as f:
        f.write(f"K={k}, Consistency={consistency} | Query time: {duration_query:.2f}s, | Read Throughput: {throughput:.2f} queries/sec\n")

    # 4. Cleanup
    send_depart_to_all()

    for p in processes:
        p.terminate()
    time.sleep(1)

def experiment_3(consistency):
    processes = []
    print(f"\n>>> ΕΚΤΕΛΕΣΗ ΠΕΙΡΑΜΑΤΟΣ 3: {consistency.upper()} (K=3)")
    
    # 1. Start Nodes
    for i in range(NUM_NODES):
        p = start_node_server(BASE_PORT + i, 3, consistency)
        processes.append(p)
    
    time.sleep(2) # Αναμονή για binding των ports

    # 2. Sequential Join (Chord Ring Formation)
    bootstrap = {"ip": IP, "port": BASE_PORT}
    for i in range(NUM_NODES):
        port = BASE_PORT + i
        try:
            requests.put(f"http://{IP}:{port}/join", params=bootstrap, timeout=10)
            time.sleep(0.5) 
        except Exception as e:
            print(f"Node {i} join failed: {e}")

    print("Ring established. Processing requests.txt...")

    # 3. Εκτέλεση Requests από τον Node 0 (Coordinator)
    results = []
    node_0_url = f"http://{IP}:{BASE_PORT}"
    
    if not os.path.exists(REQUESTS_FILE):
        print(f"Error: {REQUESTS_FILE} not found!")
        return

    with open(REQUESTS_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            
            parts = [p.strip() for p in line.split(',')]
            op = parts[0].lower()
            
            if op == "insert" and len(parts) >= 3:
                key, val = parts[1], parts[2]
                requests.post(f"{node_0_url}/insert", params={"key": key, "value": val})
            
            elif op == "query" and len(parts) >= 2:
                key = parts[1]
                try:
                    r = requests.get(f"{node_0_url}/query", params={"key": key}, timeout=5)
                    val = r.json().get("value", "NOT_FOUND") #if r.status_code == 200 else "NOT_FOUND"
                    results.append(f"Query({key}) -> {val}")
                except:
                    results.append(f"Query({key}) -> NOT_FOUND")

    # 4. Αποθήκευση αποτελεσμάτων
    output_path = f"results_experiment3_{consistency}.txt"
    with open(output_path, "w") as out:
        out.write("\n".join(results))
    
    print(f"Results saved to {output_path}")

    # 5. Cleanup
    send_depart_to_all()

    for p in processes:
        p.terminate()
    time.sleep(2)

if __name__ == "__main__":
    # Καθαρισμός προηγούμενων αποτελεσμάτων
    with open("results_experiment1.txt", "w", encoding="utf-8") as f: pass
    with open("results_experiment2.txt", "w", encoding="utf-8") as f: pass

    for c in CONSISTENCIES:
        for k in K_FACTORS:
            experiment_1_and_2(k, c)
            time.sleep(1)


    experiment_3("chain-replication") 
    experiment_3("eventually")     