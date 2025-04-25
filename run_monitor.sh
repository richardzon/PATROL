#!/bin/bash
# Run the Bittensor Chain Monitor

# Check if config file is provided
CONFIG_FILE=${1:-chain_monitor_config.json}

# Run the monitor
python bittensor_chain_monitor.py --config $CONFIG_FILE
