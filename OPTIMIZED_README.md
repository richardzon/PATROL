# Optimized Patrol Subnet Miner

This repository contains an optimized implementation of a miner for the Patrol subnet (UID 81) on the Bittensor network. The optimizations focus on maximizing performance to achieve the highest possible scores on the network.

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -e .
   ```

2. **Create a wallet** (if you don't already have one):
   ```bash
   python create_wallet.py
   ```

3. **Register on the subnet**:
   ```bash
   btcli subnet register --netuid 81 --wallet.name miners --wallet.hotkey miner_1
   ```

4. **Start the optimized miner**:
   ```bash
   chmod +x run_miner.sh
   pm2 start ./run_miner.sh --name patrol-miner
   ```

5. **Monitor your miner**:
   ```bash
   python monitor_miner.py
   ```

## Optimizations Implemented

This miner includes the following optimizations:

1. **Improved Caching**:
   - Event data caching to avoid redundant blockchain queries
   - Block hash caching for faster lookups
   - Subgraph caching to reuse previously computed results
   - Coldkey lookup caching to reduce database queries

2. **Parallel Processing**:
   - Increased concurrency for event fetching and processing
   - Batch processing of events for better memory management
   - Optimized async patterns for better resource utilization

3. **Connection Management**:
   - Robust connection handling with the substrate client
   - Automatic reconnection on failure
   - Exponential backoff for rate limiting

4. **Algorithm Improvements**:
   - More efficient graph traversal algorithms
   - Optimized data structures for faster lookups
   - Better memory management for large datasets

5. **Parameter Tuning**:
   - Increased search range for events (more blocks searched)
   - Larger batch sizes for more efficient blockchain queries
   - Optimized timeout values for better reliability

## Advanced Setup

For even better performance, set up your own archive node:

```bash
chmod +x setup_archive_node.sh
./setup_archive_node.sh
```

Then update the `run_miner.sh` script to use your local archive node:

```bash
--archive_node_address ws://localhost:9944
```

## Documentation

- `docs/optimized_mining.md`: Detailed guide on optimized mining
- `OPTIMIZATIONS.md`: List of all optimizations applied

## Troubleshooting

If you encounter the "No module named 'patrol'" error:

```bash
python install_package.py
```

This will add the current directory to your Python path.

## License

This project is licensed under the MIT License.
