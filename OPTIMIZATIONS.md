# Patrol Subnet Miner Optimizations

This document outlines all the optimizations implemented to create the best miner on the Patrol subnet network.

## Overview

The Patrol subnet miner has been optimized in several key areas:

1. **Code Optimizations**: Improved algorithms, caching, and parallel processing
2. **Parameter Tuning**: Optimized search parameters for better subgraph generation
3. **Infrastructure**: Recommendations for hardware and network setup
4. **Monitoring**: Tools to track performance and make data-driven optimizations

## Code Optimizations

### 1. Subgraph Generator Optimizations

The `subgraph_generator.py` file has been optimized with:

- **Improved caching**: Added caching for subgraphs, events, and adjacency graphs
- **Memory management**: Batch processing for better memory usage
- **Efficient data structures**: Using defaultdict and sets for faster lookups
- **Parallel processing**: Increased concurrency with configurable worker count
- **Better error handling**: More robust error recovery and logging

### 2. Event Fetcher Optimizations

The `event_fetcher.py` file has been optimized with:

- **Block hash caching**: Caching block hashes to avoid redundant queries
- **Event caching**: Storing previously fetched events to reduce blockchain queries
- **Parallel fetching**: Increased concurrency for event fetching
- **Batch optimization**: Larger batch sizes for more efficient blockchain queries
- **Connection management**: Better handling of network issues and reconnections

### 3. Event Processor Optimizations

The `event_processor.py` file has been optimized with:

- **Address caching**: Caching formatted addresses to avoid redundant processing
- **Coldkey caching**: Storing coldkey lookups to reduce database queries
- **Parallel processing**: Processing events in parallel with better concurrency
- **Batch processing**: Processing events in batches for better memory management
- **Optimized algorithms**: More efficient event processing and matching

### 4. Substrate Client Optimizations

The `substrate_client.py` file has been optimized with:

- **Query caching**: Caching query results to avoid redundant blockchain calls
- **Connection management**: Better handling of websocket connections
- **Retry logic**: Improved retry mechanisms with exponential backoff
- **Parallel initialization**: Initializing substrate instances in parallel
- **Error handling**: More robust error recovery and logging

### 5. Constants Optimization

The `constants.py` file has been updated with:

- **Increased search ranges**: Larger default values for max_future_events and max_past_events
- **Larger batch sizes**: Increased event_batch_size for more efficient blockchain queries
- **Timeout adjustments**: Longer timeouts for better reliability
- **Cache size configuration**: Configurable cache sizes for different data types

## Parameter Tuning

The following parameters have been optimized:

| Parameter | Original | Optimized | Impact |
|-----------|----------|-----------|--------|
| max_future_events | 50 | 150 | 3x more future blocks searched |
| max_past_events | 50 | 150 | 3x more past blocks searched |
| event_batch_size | 25 | 75 | 3x more efficient blockchain queries |
| semaphore limits | 1-25 | 4-50 | 2-4x more concurrent operations |
| timeout values | 3-10s | 10-60s | Better handling of slow responses |
| cache sizes | N/A | 10,000+ | Significant reduction in redundant processing |

## Infrastructure Optimizations

### 1. Own Archive Node

Setting up your own archive node provides:

- No rate limiting from shared nodes
- Faster query responses
- More reliable connections
- Ability to handle larger batch sizes

A setup script (`setup_archive_node.sh`) has been provided to automate this process.

### 2. Hardware Recommendations

Optimized hardware specifications:

- **CPU**: 8+ vCPUs for parallel processing
- **RAM**: 32GB+ for handling large datasets
- **Storage**: 1TB+ NVMe SSD for archive node and caching
- **Network**: 1Gbps+ for faster data transfer

### 3. Process Management

Using PM2 for:

- Automatic restarts on failure
- Resource monitoring
- Log management
- Performance optimization

## Monitoring and Tuning

A monitoring script (`monitor_miner.py`) has been created to:

- Track miner performance metrics
- Compare against other miners on the network
- Generate performance graphs over time
- Calculate estimated earnings
- Identify optimization opportunities

## Results

With these optimizations, you can expect:

- **Larger subgraphs**: Finding more connections between wallets
- **Faster response times**: Responding to validator requests more quickly
- **Higher scores**: Achieving better volume and responsiveness scores
- **Better reliability**: Fewer errors and more consistent performance
- **Improved ranking**: Moving up in the miner rankings

## Conclusion

By implementing these optimizations, your miner will be well-positioned to be among the best performers on the Patrol subnet network. Continue to monitor performance and make adjustments as needed to maintain your competitive edge.
