import time
import requests
import threading

SERVICES = {
    "frontend": "http://localhost:8080",
    "api-gateway": "http://localhost:8081",
    "payment-svc": "http://localhost:8082",
    "inventory-svc": "http://localhost:8083",
    "checkout-svc": "http://localhost:8084"
}

def send_traffic(name, url):
    print(f"[traffic_generator] Starting traffic loop for {name} on {url}...")
    while True:
        try:
            requests.get(url, timeout=2)
        except Exception:
            pass
        time.sleep(0.1) # 10 requests per second

def main():
    threads = []
    for name, url in SERVICES.items():
        t = threading.Thread(target=send_traffic, args=(name, url), daemon=True)
        t.start()
        threads.append(t)
    
    # Keep main thread alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
