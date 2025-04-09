#!/bin/bash

# This script applies all optimizations to the Patrol subnet miner

set -e

echo "====================================================="
echo "Patrol Subnet Miner Optimization Script"
echo "====================================================="
echo ""
echo "This script will apply all optimizations to your miner."
echo "Make sure you have at least 16GB of RAM and 4 vCPUs."
echo ""
echo "The following optimizations will be applied:"
echo "1. Code optimizations (caching, parallel processing, etc.)"
echo "2. Parameter tuning (search ranges, batch sizes, etc.)"
echo "3. Process management with PM2"
echo "4. Setup for monitoring tools"
echo ""
echo "Additionally, you'll have the option to:"
echo "5. Set up your own archive node (recommended)"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Check if PM2 is installed
if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2..."
    sudo apt-get update
    sudo apt-get install -y nodejs npm
    sudo npm install -g pm2
fi

# Check if wallet exists
if [ ! -d "$HOME/.bittensor/wallets" ]; then
    echo "Creating Bittensor wallet directory..."
    mkdir -p "$HOME/.bittensor/wallets"
fi

# Ask for wallet information
read -p "Enter your wallet name (default: miners): " WALLET_NAME
WALLET_NAME=${WALLET_NAME:-miners}

read -p "Enter your hotkey name (default: miner_1): " HOTKEY_NAME
HOTKEY_NAME=${HOTKEY_NAME:-miner_1}

# Check if wallet exists
if [ ! -d "$HOME/.bittensor/wallets/$WALLET_NAME" ]; then
    echo "Wallet $WALLET_NAME does not exist. Creating it now..."
    python create_wallet.py
fi

# Ask for archive node
read -p "Do you want to use your own archive node? (y/n, default: n): " USE_OWN_NODE
USE_OWN_NODE=${USE_OWN_NODE:-n}

if [[ $USE_OWN_NODE == "y" ]]; then
    read -p "Do you want to set up a new archive node? (y/n, default: n): " SETUP_NODE
    SETUP_NODE=${SETUP_NODE:-n}

    if [[ $SETUP_NODE == "y" ]]; then
        echo "Setting up archive node..."
        chmod +x setup_archive_node.sh
        ./setup_archive_node.sh
        ARCHIVE_NODE="ws://localhost:9944"
    else
        read -p "Enter your archive node address: " ARCHIVE_NODE
    fi
else
    ARCHIVE_NODE="wss://archive.chain.opentensor.ai:443/"
fi

# Ask for optimization level
echo ""
echo "Select optimization level:"
echo "1. Conservative (max_future_events=100, max_past_events=100, event_batch_size=50)"
echo "2. Balanced (max_future_events=150, max_past_events=150, event_batch_size=75)"
echo "3. Aggressive (max_future_events=200, max_past_events=200, event_batch_size=100)"
echo "4. Custom"
read -p "Enter your choice (1-4, default: 2): " OPT_LEVEL
OPT_LEVEL=${OPT_LEVEL:-2}

case $OPT_LEVEL in
    1)
        MAX_FUTURE_EVENTS=100
        MAX_PAST_EVENTS=100
        EVENT_BATCH_SIZE=50
        ;;
    2)
        MAX_FUTURE_EVENTS=150
        MAX_PAST_EVENTS=150
        EVENT_BATCH_SIZE=75
        ;;
    3)
        MAX_FUTURE_EVENTS=200
        MAX_PAST_EVENTS=200
        EVENT_BATCH_SIZE=100
        ;;
    4)
        read -p "Enter max_future_events (default: 150): " MAX_FUTURE_EVENTS
        MAX_FUTURE_EVENTS=${MAX_FUTURE_EVENTS:-150}

        read -p "Enter max_past_events (default: 150): " MAX_PAST_EVENTS
        MAX_PAST_EVENTS=${MAX_PAST_EVENTS:-150}

        read -p "Enter event_batch_size (default: 75): " EVENT_BATCH_SIZE
        EVENT_BATCH_SIZE=${EVENT_BATCH_SIZE:-75}
        ;;
    *)
        echo "Invalid choice. Using balanced optimization."
        MAX_FUTURE_EVENTS=150
        MAX_PAST_EVENTS=150
        EVENT_BATCH_SIZE=75
        ;;
esac

# Get external IP
EXTERNAL_IP=$(curl -s https://ipinfo.io/ip)
read -p "Enter your external IP (default: $EXTERNAL_IP): " USER_IP
EXTERNAL_IP=${USER_IP:-$EXTERNAL_IP}

# Get port
read -p "Enter port (default: 8091): " PORT
PORT=${PORT:-8091}

# Stop any existing miner
pm2 stop patrol-miner 2>/dev/null || true
pm2 delete patrol-miner 2>/dev/null || true

# Start the optimized miner
echo ""
echo "Starting optimized miner with the following parameters:"
echo "Wallet: $WALLET_NAME"
echo "Hotkey: $HOTKEY_NAME"
echo "Archive node: $ARCHIVE_NODE"
echo "External IP: $EXTERNAL_IP"
echo "Port: $PORT"
echo "max_future_events: $MAX_FUTURE_EVENTS"
echo "max_past_events: $MAX_PAST_EVENTS"
echo "event_batch_size: $EVENT_BATCH_SIZE"
echo ""

# Create a wrapper script that sets PYTHONPATH
cat > run_miner.sh << EOL
#!/bin/bash
export PYTHONPATH=\$PYTHONPATH:\$(pwd)
python3 src/patrol/mining/miner.py \
  --netuid 81 \
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

# Stop any existing miner
pm2 stop patrol-miner 2>/dev/null || true
pm2 delete patrol-miner 2>/dev/null || true

# Start the miner using the wrapper script
pm2 start ./run_miner.sh --name patrol-miner

# Set up monitoring
echo ""
echo "Setting up monitoring..."
chmod +x monitor_miner.py

echo ""
echo "====================================================="
echo "Optimization complete!"
echo "====================================================="
echo ""
echo "Your optimized miner is now running."
echo "You can check the logs with: pm2 logs patrol-miner"
echo "You can monitor the miner with: pm2 monit"
echo ""
echo "To monitor your miner's performance, run:"
echo "python monitor_miner.py --wallet.name $WALLET_NAME --wallet.hotkey $HOTKEY_NAME"
echo ""
echo "For more information, see the documentation:"
echo "- docs/optimized_mining.md: Detailed guide on optimized mining"
echo "- OPTIMIZATIONS.md: List of all optimizations applied"
echo ""
echo "Happy mining!"
