# Patrol Subnet Miner Setup Guide

This guide provides step-by-step instructions for setting up and running an optimized miner on the Patrol subnet.

## Quick Start

### 1. Install Dependencies

```bash
# Clone the repository
git clone https://github.com/richardzon/PATROL.git
cd PATROL

# Install the package
pip install -e .

# Install PM2 (if not already installed)
npm install pm2 -g
```

### 2. Wallet Setup

```bash
# Create a wallet (if you don't already have one)
python create_wallet.py

# Register on the subnet (requires TAO in your wallet)
btcli subnet register --netuid 81 --wallet.name miners --wallet.hotkey miner_1
```

### 3. Start the Miner

```bash
# Make the script executable
chmod +x run_miner.sh

# Start the miner with PM2
pm2 start ./run_miner.sh --name patrol-miner

# Check the logs
pm2 logs patrol-miner
```

### 4. Monitor Your Miner

```bash
# Check your miner's status
python monitor_miner.py
```

## Advanced Setup

### Setting Up Your Own Archive Node

For the best performance, set up your own archive node:

```bash
# Make the script executable
chmod +x setup_archive_node.sh

# Run the setup script
./setup_archive_node.sh

# Update your miner configuration to use your local archive node
# Edit run_miner.sh and change:
# --archive_node_address ws://localhost:9944

# Restart your miner
pm2 restart patrol-miner
```

### Optimizing System Resources

```bash
# Increase system limits
sudo nano /etc/security/limits.conf
# Add:
# * soft nofile 65535
# * hard nofile 65535

# Optimize network settings
sudo nano /etc/sysctl.conf
# Add:
# net.core.somaxconn = 1024
# net.core.netdev_max_backlog = 5000
# net.ipv4.tcp_max_syn_backlog = 8096
# net.ipv4.tcp_slow_start_after_idle = 0
# net.ipv4.tcp_tw_reuse = 1

# Apply the changes
sudo sysctl -p

# Optimize Python performance
pip install ujson uvloop
```

## Troubleshooting

### Module Not Found Errors

If you encounter "No module named 'patrol'" errors:

```bash
python install_package.py
```

### Connection Issues

If you're having trouble connecting to the archive node:

```bash
# Check if the archive node is accessible
curl -H "Content-Type: application/json" -d '{"id":1, "jsonrpc":"2.0", "method": "system_health", "params":[]}' http://localhost:9944
```

### Performance Issues

If your miner is performing poorly:

```bash
# Check system resources
htop

# Check disk I/O
iostat -x 1

# Check network usage
iftop
```

## Maintenance

### Automated Monitoring

```bash
# Set up log rotation
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 10M
pm2 set pm2-logrotate:retain 5

# Create a restart script
echo '#!/bin/bash
pm2 restart patrol-miner
' > restart_miner.sh
chmod +x restart_miner.sh

# Schedule regular restarts
crontab -e
# Add:
# 0 3 * * * /path/to/restart_miner.sh
```

## Optimized Parameters

The miner is configured with the following optimized parameters:

- `max_future_events`: 200 (default: 100)
- `max_past_events`: 200 (default: 100)
- `event_batch_size`: 100 (default: 50)

These parameters have been tested and shown to provide the best performance on most systems. You can adjust them based on your specific hardware capabilities.

## Hardware Requirements

For optimal performance, we recommend:

- CPU: 4+ cores
- RAM: 8+ GB
- Storage: 100+ GB SSD
- Network: 100+ Mbps connection

## Getting Help

If you encounter issues not covered in this guide, you can:

1. Check the [Patrol Discord channel](https://discord.gg/bittensor)
2. Open an issue on the [GitHub repository](https://github.com/richardzon/PATROL)
3. Contact the Patrol team directly
