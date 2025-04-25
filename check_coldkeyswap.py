#!/usr/bin/env python3
# check_coldkeyswap.py - Script to check for scheduled coldkey swaps

import json
import argparse
from datetime import datetime, timedelta

def load_coldkey_swaps(file_path="coldkey_swaps.log"):
    """Load coldkey swaps from the log file"""
    swaps = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                try:
                    swap = json.loads(line.strip())
                    swaps.append(swap)
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse line: {line}")
    except FileNotFoundError:
        print(f"Warning: Coldkey swaps log file not found at {file_path}")

    return swaps

def filter_swaps_by_time(swaps, hours=24):
    """Filter swaps by time (last N hours)"""
    cutoff_time = datetime.now() - timedelta(hours=hours)
    recent_swaps = []

    for swap in swaps:
        try:
            swap_time = datetime.fromisoformat(swap.get('timestamp', ''))
            if swap_time >= cutoff_time:
                recent_swaps.append(swap)
        except (ValueError, TypeError):
            # Skip entries with invalid timestamps
            continue

    return recent_swaps

def filter_swaps_by_subnet(swaps, subnet_id):
    """Filter swaps by subnet ID"""
    filtered_swaps = []

    for swap in swaps:
        owned_subnets = swap.get('owned_subnets', [])
        if subnet_id in owned_subnets:
            filtered_swaps.append(swap)

    return filtered_swaps

def print_subnet_info(swaps):
    """Print information about subnets with scheduled coldkey swaps"""
    if not swaps:
        print("No scheduled coldkey swaps found.")
        return

    print(f"Found {len(swaps)} scheduled coldkey swap(s):")
    print("-" * 60)

    for i, swap in enumerate(swaps, 1):
        # Extract data
        block_number = swap.get('block_number', 'Unknown')
        source = swap.get('source_coldkey', 'Unknown')
        destination = swap.get('destination_coldkey', 'Unknown')
        subnets = swap.get('owned_subnets', [])
        timestamp = swap.get('timestamp', 'Unknown')

        # Format source and destination for display
        source_display = source
        if len(source) > 20:
            source_display = f"{source[:10]}...{source[-6:]}"

        destination_display = destination
        if len(destination) > 20:
            destination_display = f"{destination[:10]}...{destination[-6:]}"

        # Print swap details
        print(f"Swap #{i}:")
        print(f"  Block: {block_number}")
        print(f"  Time: {timestamp}")
        print(f"  Source: {source_display}")
        print(f"  Destination: {destination_display}")
        print(f"  Affected Subnets: {', '.join(map(str, subnets))}")
        print("-" * 60)

def main():
    parser = argparse.ArgumentParser(description="Check for scheduled coldkey swaps")
    parser.add_argument("--file", default="coldkey_swaps.log", help="Path to coldkey swaps log file")
    parser.add_argument("--hours", type=int, default=24, help="Show swaps from the last N hours")
    parser.add_argument("--subnet", type=int, help="Filter by subnet ID")
    args = parser.parse_args()

    # Load all swaps
    all_swaps = load_coldkey_swaps(args.file)

    # Filter by time
    filtered_swaps = filter_swaps_by_time(all_swaps, args.hours)

    # Filter by subnet if specified
    if args.subnet is not None:
        filtered_swaps = filter_swaps_by_subnet(filtered_swaps, args.subnet)
        print(f"Filtering for subnet {args.subnet}")

    # Print subnet information
    print_subnet_info(filtered_swaps)

if __name__ == "__main__":
    main()
