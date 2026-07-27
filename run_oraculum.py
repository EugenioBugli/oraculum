import sys
import time
import webbrowser
from src.control_server import ControlServer

def main():
    print("[*] Starting Oraculum Web Gateway...")
    server = ControlServer()
    server.start()
    
    # Allow the server a moment to spin up HTTP & socket ports
    time.sleep(0.5)
    
    url = "http://localhost:8080/index.html"
    print(f"[*] Opening browser to {url}...")
    try:
        # Open in default web browser
        webbrowser.open(url)
    except Exception as e:
        print(f"[Warning] Failed to auto-open web browser: {e}")
        
    print(f"\n[*] Oraculum Gateway is live at: {url}")
    print("[*] Press Ctrl+C to terminate the visualizer.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[*] Shutting down Oraculum...")
        server.stop()
        print("[*] Done. Clean exit.")

if __name__ == "__main__":
    main()
