#!/usr/bin/env python3
# test_coldkey_swap.py - Test script for coldkey swap logging

import json
from datetime import datetime

def simulate_coldkey_swap():
    """Simulate a coldkey swap event and log it to the coldkey_swaps.log file"""
    # Create a test coldkey swap event
    coldkey_swap_data = {
        "block_number": 5432100,
        "source_coldkey": "5FQrUJStrGYMiTjP8onhXQHcP3toWacxR1ZccNibN6q6zgig",
        "destination_coldkey": "5CniE3mb77BhbuXCDN2aiDGWfWsqbeV6o5QfhvN3gbvhozyt",
        "owned_subnets": [12, 14, 16],  # Example subnets
        "timestamp": datetime.now().isoformat()
    }
    
    # Write to the coldkey swaps log file
    with open("coldkey_swaps.log", "a") as f:
        f.write(json.dumps(coldkey_swap_data) + "\n")
    
    print(f"Simulated coldkey swap logged to coldkey_swaps.log")
    print(f"Source: {coldkey_swap_data['source_coldkey']}")
    print(f"Destination: {coldkey_swap_data['destination_coldkey']}")
    print(f"Affected Subnets: {coldkey_swap_data['owned_subnets']}")
    
    print("\nYou can now run ./check_coldkeyswap.py to see the logged swap.")

if __name__ == "__main__":
    simulate_coldkey_swap()
