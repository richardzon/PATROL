#!/bin/bash

# This script starts the optimized Patrol subnet miner

# Default values
WALLET_NAME="miners"
HOTKEY_NAME="miner_1"
NETUID=81
PORT=8091
EXTERNAL_IP=$(curl -s https://ipinfo.io/ip)
ARCHIVE_NODE="wss://archive.chain.opentensor.ai:443/"
MAX_FUTURE_EVENTS=150
MAX_PAST_EVENTS=150
EVENT_BATCH_SIZE=75

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --wallet_name)
      WALLET_NAME="$2"
      shift 2
      ;;
    --hotkey_name)
      HOTKEY_NAME="$2"
      shift 2
      ;;
    --netuid)
      NETUID="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --external_ip)
      EXTERNAL_IP="$2"
      shift 2
      ;;
    --archive_node)
      ARCHIVE_NODE="$2"
      shift 2
      ;;
    --max_future_events)
      MAX_FUTURE_EVENTS="$2"
      shift 2
      ;;
    --max_past_events)
      MAX_PAST_EVENTS="$2"
      shift 2
      ;;
    --event_batch_size)
      EVENT_BATCH_SIZE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Install PM2 if not already installed
if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2..."
    sudo apt-get update
    sudo apt-get install -y nodejs npm
    sudo npm install -g pm2
fi

# Check if wallet exists
if [ ! -d "$HOME/.bittensor/wallets/$WALLET_NAME" ]; then
    echo "Wallet $WALLET_NAME does not exist. Please create it first."
    exit 1
fi

# Check if hotkey exists
if [ ! -f "$HOME/.bittensor/wallets/$WALLET_NAME/hotkeys/$HOTKEY_NAME" ]; then
    echo "Hotkey $HOTKEY_NAME does not exist. Please create it first."
    exit 1
fi

# Stop any existing miner
pm2 stop patrol-miner 2>/dev/null || true
pm2 delete patrol-miner 2>/dev/null || true

# Start the optimized miner
echo "Starting optimized Patrol subnet miner..."
echo "Using wallet: $WALLET_NAME"
echo "Using hotkey: $HOTKEY_NAME"
echo "Using netuid: $NETUID"
echo "Using port: $PORT"
echo "Using external IP: $EXTERNAL_IP"
echo "Using archive node: $ARCHIVE_NODE"
echo "Using max_future_events: $MAX_FUTURE_EVENTS"
echo "Using max_past_events: $MAX_PAST_EVENTS"
echo "Using event_batch_size: $EVENT_BATCH_SIZE"

# Create a wrapper script that sets PYTHONPATH
cat > run_miner.sh << EOL
#!/bin/bash
export PYTHONPATH=\$PYTHONPATH:\$(pwd)
python3 src/patrol/mining/miner.py \
  --netuid $NETUID \
  --wallet.name $WALLET_NAME \
  --wallet.hotkey $HOTKEY_NAME \
  --archive_node_address $ARCHIVE_NODE \
  --external_ip $EXTERNAL_IP \
  --port $PORT \
  --max_future_events $MAX_FUTURE_EVENTS \
  --max_past_events $MAX_PAST_EVENTS \
  --event_batch_size $EVENT_BATCH_SIZE \
  --logging.debug
EOL

chmod +x run_miner.sh

# Start the miner using the wrapper script
pm2 start ./run_miner.sh --name patrol-miner

echo "Miner started! You can check the logs with: pm2 logs patrol-miner"
echo "You can monitor the miner with: pm2 monit"
