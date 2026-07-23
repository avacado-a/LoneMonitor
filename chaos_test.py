import sys
import time
import requests

BASE_URL = "http://127.0.0.1:5000"

def test_keyerror_injection():
    print("\n--- Chaos Scenario 1: Injecting KeyError / Null Pointer ---")
    print("Sending malformed payload (missing 'user_id') to POST /user...")
    try:
        r = requests.post(f"{BASE_URL}/user", json={"invalid_key": "abc"}, timeout=3)
        print(f"Response Status: {r.status_code}")
        print(f"Response Text: {r.text}")
    except Exception as e:
        print(f"Request failed as expected: {e}")

def test_memory_leak_injection():
    print("\n--- Chaos Scenario 2: Injecting Memory Leak ---")
    print("Calling /chaos/leak multiple times to saturate memory...")
    for i in range(5):
        try:
            r = requests.get(f"{BASE_URL}/chaos/leak", timeout=3)
            print(f"Leak call {i+1}: {r.json()}")
        except Exception as e:
            print(f"Leak call {i+1} failed: {e}")

def test_stale_lock_crash_injection():
    print("\n--- Chaos Scenario 3: Injecting Violent Crash & Stale Lock ---")
    print("Calling /chaos/lock-crash...")
    try:
        r = requests.get(f"{BASE_URL}/chaos/lock-crash", timeout=3)
        print(r.text)
    except Exception as e:
        print(f"Process crashed as expected: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "keyerror":
            test_keyerror_injection()
        elif cmd == "leak":
            test_memory_leak_injection()
        elif cmd == "lock":
            test_stale_lock_crash_injection()
        else:
            print("Unknown chaos command. Options: keyerror, leak, lock")
    else:
        print("Usage: python chaos_test.py [keyerror|leak|lock]")
