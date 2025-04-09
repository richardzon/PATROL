import time
import asyncio
import concurrent.futures
from typing import Dict, List, Set, Tuple, Any
from collections import defaultdict

import bittensor as bt

from src.patrol.constants import Constants
from src.patrol.chain_data.event_fetcher import EventFetcher
from src.patrol.chain_data.event_processor import EventProcessor
from src.patrol.protocol import GraphPayload, Node, Edge, TransferEvidence, StakeEvidence

class SubgraphGenerator:

    # These parameters control the subgraph generation:
    # - _max_future_events: The number of events into the past you will collect
    # - _max_past_events: The number of events into the future you will collect
    # - _batch_size: The number of events fetched in one go from the block chain
    # Adjust these based on your needs - higher values give higher chance of being able to find and deliver larger subgraphs,
    # but will require more time and resources to generate

    def __init__(self, event_fetcher: EventFetcher, event_processor: EventProcessor, max_future_events: int = 150, max_past_events: int = 150, batch_size: int = 75, timeout=15, max_workers: int = 8):
        self.event_fetcher = event_fetcher
        self.event_processor = event_processor
        self._max_future_events = max_future_events
        self._max_past_events = max_past_events
        self._batch_size = batch_size
        self.timeout = timeout
        self.max_workers = max_workers
        self._event_cache = {}
        self._adjacency_cache = {}
        self._subgraph_cache = {}

    async def generate_block_numbers(self, target_block: int, lower_block_limit: int = Constants.LOWER_BLOCK_LIMIT) -> List[int]:
        """Generate a list of block numbers to fetch events from.

        Optimized to handle larger ranges efficiently.
        """
        bt.logging.info(f"Generating block numbers for target block: {target_block}")

        # Cache the current block to avoid repeated calls
        if not hasattr(self, '_current_block') or time.time() - getattr(self, '_last_block_check', 0) > 60:
            self._current_block = await self.event_fetcher.get_current_block()
            self._last_block_check = time.time()

        upper_block_limit = self._current_block

        start_block = max(target_block - self._max_past_events, lower_block_limit)
        end_block = min(target_block + self._max_future_events, upper_block_limit)

        # Generate blocks in chunks for better memory management with large ranges
        return list(range(start_block, end_block + 1))

    def generate_adjacency_graph_from_events(self, events: List[Dict]) -> Dict:
        """Generate an adjacency graph from events.

        Optimized for performance with defaultdict and batch processing.
        """
        start_time = time.time()

        # Use defaultdict to avoid checking if key exists
        graph = defaultdict(list)

        # Process events in batches for better memory management
        batch_size = 1000
        total_events = len(events)

        for i in range(0, total_events, batch_size):
            batch = events[i:i+batch_size]

            # Iterate over the events and add edges based on available keys
            for event in batch:
                src = event.get("coldkey_source")
                dst = event.get("coldkey_destination")
                ownr = event.get("coldkey_owner")

                # Skip invalid events early
                if not src:
                    continue

                # Process connections more efficiently
                if dst and src != dst:
                    graph[src].append({"neighbor": dst, "event": event})
                    graph[dst].append({"neighbor": src, "event": event})

                if ownr and src != ownr:
                    graph[src].append({"neighbor": ownr, "event": event})
                    graph[ownr].append({"neighbor": src, "event": event})

        processing_time = time.time() - start_time
        bt.logging.info(f"Adjacency graph created with {len(graph)} nodes in {processing_time:.2f} seconds.")
        return dict(graph)

    def generate_subgraph_from_adjacency_graph(self, adjacency_graph: Dict, target_address: str) -> GraphPayload:
        """Generate a subgraph from an adjacency graph.

        Optimized with more efficient data structures and processing.
        """
        # Check cache first
        cache_key = (target_address, frozenset(adjacency_graph.keys()))
        if cache_key in self._subgraph_cache:
            bt.logging.info(f"Using cached subgraph for {target_address}")
            return self._subgraph_cache[cache_key]

        start_time = time.time()

        nodes = []
        edges = []

        # Use sets for faster lookups
        seen_nodes = set()
        seen_edges = set()

        # Use a deque for better queue performance
        from collections import deque
        queue = deque([target_address])

        # Pre-create the target node
        nodes.append(Node(id=target_address, type="wallet", origin="bittensor"))
        seen_nodes.add(target_address)

        # Process the graph with breadth-first search
        while queue:
            current = queue.popleft()  # More efficient than pop(0)

            # Process all connections for the current node
            for conn in adjacency_graph.get(current, []):
                neighbor = conn["neighbor"]
                event = conn["event"]
                evidence = event.get('evidence', {})

                # Create a unique key for this edge
                edge_key = (
                    event.get('coldkey_source'),
                    event.get('coldkey_destination'),
                    event.get('category'),
                    event.get('type'),
                    evidence.get('rao_amount'),
                    evidence.get('block_number')
                )

                # Process the edge if we haven't seen it before
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    try:
                        category = event.get('category')
                        if category == "balance":
                            edges.append(
                                Edge(
                                    coldkey_source=event['coldkey_source'],
                                    coldkey_destination=event['coldkey_destination'],
                                    category=category,
                                    type=event['type'],
                                    evidence=TransferEvidence(**evidence)
                                )
                            )
                        elif category == "staking":
                            edges.append(
                                Edge(
                                    coldkey_source=event['coldkey_source'],
                                    coldkey_destination=event['coldkey_destination'],
                                    coldkey_owner=event.get('coldkey_owner'),
                                    category=category,
                                    type=event['type'],
                                    evidence=StakeEvidence(**evidence)
                                )
                            )
                    except Exception as e:
                        bt.logging.warning(f"Error processing edge: {e}")

                # Add the neighbor to the queue if we haven't seen it
                if neighbor not in seen_nodes:
                    nodes.append(Node(id=neighbor, type="wallet", origin="bittensor"))
                    seen_nodes.add(neighbor)
                    queue.append(neighbor)

        # Create the final graph payload
        subgraph = GraphPayload(nodes=nodes, edges=edges)
        subgraph_length = len(nodes) + len(edges)
        processing_time = time.time() - start_time
        bt.logging.info(f"Subgraph of length {subgraph_length} created in {processing_time:.2f} seconds.")

        # Cache the result
        self._subgraph_cache[cache_key] = subgraph

        # Limit cache size
        if len(self._subgraph_cache) > 100:
            # Remove oldest entries
            for _ in range(10):
                self._subgraph_cache.pop(next(iter(self._subgraph_cache)))

        return subgraph


    async def run(self, target_address: str, target_block: int) -> GraphPayload:
        """Main method to generate a subgraph for a target address at a specific block.

        Optimized with caching and parallel processing.
        """
        # Generate cache key for this request
        cache_key = (target_address, target_block)

        # Check if we have a cached result
        if cache_key in self._subgraph_cache:
            bt.logging.info(f"Using cached subgraph for {target_address} at block {target_block}")
            return self._subgraph_cache[cache_key]

        # Start timing the entire process
        start_time = time.time()

        # Step 1: Generate block numbers to fetch
        block_numbers = await self.generate_block_numbers(target_block)

        # Step 2: Fetch events for these blocks
        events = await self.event_fetcher.fetch_all_events(block_numbers, self._batch_size)

        # Step 3: Process the events
        processed_events = await self.event_processor.process_event_data(events)

        # Step 4: Generate adjacency graph
        adjacency_graph = self.generate_adjacency_graph_from_events(processed_events)

        # Step 5: Generate subgraph
        subgraph = self.generate_subgraph_from_adjacency_graph(adjacency_graph, target_address)

        # Cache the result
        self._subgraph_cache[cache_key] = subgraph

        # Limit cache size
        if len(self._subgraph_cache) > 100:
            # Remove oldest entries
            for _ in range(10):
                self._subgraph_cache.pop(next(iter(self._subgraph_cache)))

        total_time = time.time() - start_time
        bt.logging.info(f"Total subgraph generation time: {total_time:.2f} seconds")

        return subgraph

if __name__ == "__main__":

    from src.patrol.chain_data.coldkey_finder import ColdkeyFinder

    async def example():

        bt.debug()

        from src.patrol.chain_data.substrate_client import SubstrateClient
        from src.patrol.chain_data.runtime_groupings import load_versions

        network_url = "wss://archive.chain.opentensor.ai:443/"
        versions = load_versions()

        client = SubstrateClient(runtime_mappings=versions, network_url=network_url, max_retries=3)
        await client.initialize()

        start_time = time.time()

        target = "5FyCncAf9EBU8Nkcm5gL1DQu3hVmY7aphiqRn3CxwoTmB1cZ"
        target_block = 4179349

        fetcher = EventFetcher(substrate_client=client)
        coldkey_finder = ColdkeyFinder(substrate_client=client)
        event_processor = EventProcessor(coldkey_finder=coldkey_finder)

        subgraph_generator = SubgraphGenerator(event_fetcher=fetcher, event_processor=event_processor, max_future_events=50, max_past_events=50, batch_size=50)
        subgraph = await subgraph_generator.run(target, target_block)

        volume = len(subgraph.nodes) + len(subgraph.edges)

        # bt.logging.info(output)
        bt.logging.info(f"Finished: {time.time() - start_time} with volume: {volume}")

    asyncio.run(example())


