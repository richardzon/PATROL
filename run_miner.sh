#!/bin/bash

# Add the current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Run the miner with optimized parameters
python3 src/patrol/mining/miner.py \
  --netuid 81 \
  --wallet_path ~/.bittensor/wallets/miners \
  --coldkey miners \
  --hotkey miner_1 \
  --archive_node_address wss://archive.chain.opentensor.ai:443/ \
  --external_ip $(curl -s https://ipinfo.io/ip) \
  --port 8091 \
  --max_future_events 200 \
  --max_past_events 200 \
  --event_batch_size 100
