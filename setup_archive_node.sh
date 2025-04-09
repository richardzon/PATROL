#!/bin/bash

# This script sets up a Bittensor archive node for optimal mining performance
# It requires at least 500GB of free disk space and 16GB of RAM

set -e

echo "Setting up Bittensor archive node for optimal mining performance..."

# Install dependencies
echo "Installing dependencies..."
sudo apt-get update
sudo apt-get install -y build-essential git clang curl libssl-dev llvm libudev-dev make protobuf-compiler

# Install Rust
echo "Installing Rust..."
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env
rustup default stable
rustup update nightly
rustup target add wasm32-unknown-unknown --toolchain nightly

# Clone the Bittensor repository
echo "Cloning Bittensor repository..."
git clone https://github.com/opentensor/subtensor.git
cd subtensor

# Build the node
echo "Building the node (this may take a while)..."
cargo build --release

# Create service file
echo "Creating systemd service file..."
sudo tee /etc/systemd/system/bittensor-archive.service > /dev/null << EOL
[Unit]
Description=Bittensor Archive Node
After=network.target

[Service]
Type=simple
User=$USER
ExecStart=$(pwd)/target/release/node-subtensor --base-path /data/bittensor --chain finney --name "PatrolMinerArchiveNode" --pruning archive --rpc-cors all --rpc-methods unsafe --rpc-external --ws-external
Restart=always
RestartSec=3
LimitNOFILE=10000

[Install]
WantedBy=multi-user.target
EOL

# Create data directory
echo "Creating data directory..."
sudo mkdir -p /data/bittensor
sudo chown -R $USER:$USER /data/bittensor

# Enable and start the service
echo "Enabling and starting the service..."
sudo systemctl daemon-reload
sudo systemctl enable bittensor-archive
sudo systemctl start bittensor-archive

echo "Archive node setup complete!"
echo "The node will now start syncing the blockchain. This will take several days."
echo "You can check the status with: sudo systemctl status bittensor-archive"
echo "You can view the logs with: sudo journalctl -u bittensor-archive -f"
echo ""
echo "Once synced, you can use this node with your miner by setting:"
echo "--archive_node_address ws://localhost:9944"
