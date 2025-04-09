# Optimized Mining Guide for Patrol Subnet

This guide provides detailed instructions for setting up and running an optimized miner for the Patrol subnet. These optimizations are designed to maximize your performance and achieve the highest possible scores on the network.

## Table of Contents
- [Hardware Requirements](#hardware-requirements)
- [Setting Up Your Environment](#setting-up-your-environment)
- [Setting Up Your Own Archive Node](#setting-up-your-own-archive-node)
- [Optimized Miner Configuration](#optimized-miner-configuration)
- [Monitoring Performance](#monitoring-performance)
- [Troubleshooting](#troubleshooting)
- [Advanced Optimizations](#advanced-optimizations)

## Hardware Requirements

For optimal performance, we recommend the following hardware specifications:

| Component | Minimum | Recommended | Optimal |
|-----------|---------|-------------|---------|
| CPU | 2 vCPUs | 4 vCPUs | 8+ vCPUs |
| RAM | 8GB | 16GB | 32GB+ |
| Storage | 100GB SSD | 500GB SSD | 1TB+ NVMe SSD |
| Network | 100 Mbps | 1 Gbps | 10 Gbps |

The Patrol subnet is resource-intensive, especially when processing large subgraphs. More powerful hardware will allow you to process more blocks and find more connections, resulting in higher scores.

## Setting Up Your Environment

1. **Clone the repository**:
   ```bash
   git clone https://github.com/tensora-ai/patrol_subnet.git
   cd patrol_subnet
   ```

2. **Install dependencies**:
   ```bash
   pip install -e .
   ```

3. **Create a wallet** (if you don't already have one):
   ```bash
   python create_wallet.py
   ```
   This will create a wallet with the name "miners" and a hotkey "miner_1".

4. **Register on the subnet**:
   ```bash
   btcli subnet register --netuid 81 --wallet.name miners --wallet.hotkey miner_1
   ```

## Setting Up Your Own Archive Node

One of the most significant optimizations you can make is setting up your own archive node. This will eliminate rate limiting and provide faster, more reliable access to blockchain data.

1. **Run the setup script**:
   ```bash
   chmod +x setup_archive_node.sh
   ./setup_archive_node.sh
   ```

2. **Monitor the sync progress**:
   ```bash
   sudo journalctl -u bittensor-archive -f
   ```

The sync process can take several days, but it's worth the wait. While syncing, you can still run your miner using the public archive node.

## Optimized Miner Configuration

Our optimized miner includes several improvements:

1. **Enhanced caching**: Reduces redundant blockchain queries
2. **Parallel processing**: Increases throughput for event fetching and processing
3. **Improved connection management**: Better handling of network issues
4. **Optimized algorithms**: More efficient graph traversal and data structures
5. **Parameter tuning**: Optimized search ranges and batch sizes

To start the optimized miner:

```bash
chmod +x start_optimized_miner.sh
./start_optimized_miner.sh
```

You can customize the parameters by editing the script or passing command-line arguments:

```bash
./start_optimized_miner.sh --wallet_name your_wallet --hotkey_name your_hotkey --archive_node ws://your_archive_node:9944
```

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| max_future_events | 150 | Number of blocks to search ahead of the target block |
| max_past_events | 150 | Number of blocks to search behind the target block |
| event_batch_size | 75 | Number of blocks to query at once |

These parameters can be adjusted based on your hardware capabilities. Higher values will result in more comprehensive subgraphs but require more resources.

## Monitoring Performance

We've created a monitoring script to help you track your miner's performance:

```bash
chmod +x monitor_miner.py
python monitor_miner.py
```

This will show:
- Your current rank, trust, and incentive scores
- Your position relative to other miners
- Estimated daily earnings
- Performance trends over time

The script also generates a graph showing your performance metrics over time, which can help you identify trends and optimize your configuration.

## Troubleshooting

### Common Issues

1. **Rate limiting errors**:
   - Set up your own archive node
   - Reduce batch sizes temporarily
   - Implement exponential backoff (already included in our optimized code)

2. **Memory issues**:
   - Reduce max_future_events and max_past_events
   - Upgrade your RAM
   - Enable swap space (not recommended for long-term use)

3. **Slow response times**:
   - Check your network connection
   - Ensure your archive node is healthy
   - Optimize your hardware for better performance

4. **Low scores**:
   - Increase max_future_events and max_past_events to find more connections
   - Ensure your miner is running continuously
   - Check for any validation errors in the logs

### Checking Logs

```bash
pm2 logs patrol-miner
```

## Advanced Optimizations

For those looking to squeeze out every bit of performance:

1. **Database Optimizations**:
   - Use a high-performance database for caching event data
   - Implement efficient indexing strategies
   - Consider using Redis for in-memory caching

2. **Network Optimizations**:
   - Use a CDN or edge server close to the Bittensor network
   - Implement connection pooling for substrate queries
   - Optimize TCP/IP settings for your server

3. **Load Balancing**:
   - Run multiple miners behind a load balancer
   - Distribute requests across multiple instances
   - Use different archive nodes for redundancy

4. **Custom Subgraph Generation**:
   - Implement more efficient graph algorithms
   - Optimize memory usage during graph traversal
   - Use specialized data structures for faster lookups

Remember, the key to success in the Patrol subnet is finding the right balance between comprehensive data collection and fast response times. Continuously monitor your performance and adjust your configuration accordingly.

Happy mining!
