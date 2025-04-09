import asyncio
import logging
import time
from typing import Dict, List, Tuple, Any, Optional, Set
from functools import lru_cache

import bittensor as bt
from async_substrate_interface import AsyncSubstrateInterface
from src.patrol.chain_data.runtime_groupings import group_blocks

class EventFetcher:
    def __init__(self, substrate_client):
        self.substrate_client = substrate_client
        self.semaphore = asyncio.Semaphore(4)  # Increased concurrency
        self._block_hash_cache = {}  # Cache for block hashes
        self._event_cache = {}  # Cache for events
        self._current_block = None
        self._last_block_check = 0

    async def get_current_block(self) -> int:
        """Get the current block number with caching."""
        # Cache the current block for 60 seconds to reduce API calls
        current_time = time.time()
        if self._current_block is None or current_time - self._last_block_check > 60:
            current_block = await self.substrate_client.query("get_block", None)
            self._current_block = current_block["header"]["number"]
            self._last_block_check = current_time
            bt.logging.debug(f"Updated current block to {self._current_block}")
        return self._current_block

    async def get_block_events(
        self,
        runtime_version: int,
        block_info: List[Tuple[int, str]],
        max_concurrent: int = 20  # Increased concurrency
    ) -> Dict[int, Any]:
        """
        Fetch events for a batch of blocks for a specific runtime_version using the substrate client's query method.
        Optimized with caching and better error handling.
        """
        # Check cache first and filter out blocks we already have
        cached_results = {}
        uncached_block_info = []

        for block_number, block_hash in block_info:
            cache_key = (runtime_version, block_number)
            if cache_key in self._event_cache:
                cached_results[block_number] = self._event_cache[cache_key]
            else:
                uncached_block_info.append((block_number, block_hash))

        # If all blocks are cached, return immediately
        if not uncached_block_info:
            return cached_results

        # Extract block hashes for processing
        block_hashes = [block_hash for (_, block_hash) in uncached_block_info]
        semaphore = asyncio.Semaphore(max_concurrent)

        async def preprocess_with_semaphore(block_hash):
            async with semaphore:
                try:
                    # Use the query method to call the substrate's _preprocess method
                    return await self.substrate_client.query(
                        "_preprocess",
                        runtime_version,
                        None,
                        block_hash,
                        module="System",
                        storage_function="Events"
                    )
                except Exception as e:
                    bt.logging.warning(f"Preprocessing failed for block hash {block_hash}: {e}")
                    return e

        # Process blocks in parallel with better error handling
        tasks = [preprocess_with_semaphore(h) for h in block_hashes]
        preprocessed_lst = await asyncio.gather(*tasks)

        # Filter out errors and their corresponding blocks
        valid_preprocessed = []
        valid_block_info = []
        valid_block_hashes = []

        for i, (result, block_data) in enumerate(zip(preprocessed_lst, uncached_block_info)):
            if not isinstance(result, Exception):
                valid_preprocessed.append(result)
                valid_block_info.append(block_data)
                valid_block_hashes.append(block_hashes[i])

        # If no valid blocks remain, return just the cached results
        if not valid_block_info:
            return cached_results

        # Create payloads for valid blocks
        payloads = [
            AsyncSubstrateInterface.make_payload(
                str(block_hash),
                preprocessed.method,
                [preprocessed.params[0], block_hash]
            )
            for block_hash, preprocessed in zip(valid_block_hashes, valid_preprocessed)
        ]

        try:
            # Increased timeout for larger batches
            responses = await asyncio.wait_for(
                self.substrate_client.query(
                    "_make_rpc_request",
                    runtime_version,
                    payloads,
                    valid_preprocessed[0].value_scale_type,
                    valid_preprocessed[0].storage_item
                ),
                timeout=10  # Increased timeout
            )

            # Build a mapping from block_number to event response and update cache
            new_results = {}
            for (block_number, block_hash) in valid_block_info:
                if block_hash in responses:
                    result = responses[block_hash][0]
                    new_results[block_number] = result
                    # Cache the result
                    self._event_cache[(runtime_version, block_number)] = result

            # Combine cached and new results
            combined_results = {**cached_results, **new_results}

            # Limit cache size to prevent memory issues
            if len(self._event_cache) > 10000:
                # Remove oldest 1000 entries
                keys_to_remove = list(self._event_cache.keys())[:1000]
                for key in keys_to_remove:
                    self._event_cache.pop(key, None)

            return combined_results

        except Exception as e:
            bt.logging.error(f"Error fetching events: {e}")
            # Return whatever we have from cache
            return cached_results

    async def fetch_all_events(self, block_numbers: List[int], batch_size: int = 75) -> Dict[int, Any]:
        """
        Retrieve events for all given block numbers.
        Optimized with caching, parallel processing, and better error handling.
        """
        start_time = time.time()

        if not block_numbers:
            bt.logging.warning("No block numbers provided. Returning empty event dictionary.")
            return {}

        if any(not isinstance(b, int) for b in block_numbers):
            bt.logging.warning("Non-integer value found in block_numbers. Returning empty event dictionary.")
            return {}

        # Convert to set for faster lookups and remove duplicates
        block_numbers = set(block_numbers)

        # Check which blocks we already have in cache
        cached_events = {}
        uncached_blocks = set()

        for block_num in block_numbers:
            # Check if we have this block in any runtime version cache
            found = False
            for runtime_version in range(100, 300):  # Typical range of runtime versions
                if (runtime_version, block_num) in self._event_cache:
                    cached_events[block_num] = self._event_cache[(runtime_version, block_num)]
                    found = True
                    break
            if not found:
                uncached_blocks.add(block_num)

        # If all blocks are cached, return immediately
        if not uncached_blocks:
            bt.logging.info(f"All {len(block_numbers)} blocks found in cache")
            return cached_events

        async with self.semaphore:
            bt.logging.info(f"Fetching event data for {len(uncached_blocks)} uncached blocks out of {len(block_numbers)} total")

            # Get block hashes with caching
            block_hash_map = {}
            hash_fetch_tasks = []

            for block_num in uncached_blocks:
                if block_num in self._block_hash_cache:
                    block_hash_map[block_num] = self._block_hash_cache[block_num]
                else:
                    hash_fetch_tasks.append((block_num, self.substrate_client.query("get_block_hash", None, block_num)))

            # Execute hash fetch tasks
            for block_num, task in hash_fetch_tasks:
                try:
                    block_hash = await task
                    block_hash_map[block_num] = block_hash
                    self._block_hash_cache[block_num] = block_hash  # Cache the hash
                except Exception as e:
                    bt.logging.warning(f"Failed to get hash for block {block_num}: {e}")

            # Limit block hash cache size
            if len(self._block_hash_cache) > 10000:
                keys_to_remove = list(self._block_hash_cache.keys())[:1000]
                for key in keys_to_remove:
                    self._block_hash_cache.pop(key, None)

            # Get current block
            current_block = await self.get_current_block()

            # Group blocks by runtime version
            block_numbers_list = list(block_hash_map.keys())
            block_hashes_list = [block_hash_map[bn] for bn in block_numbers_list]

            versions = self.substrate_client.return_runtime_versions()
            grouped = group_blocks(block_numbers_list, block_hashes_list, current_block, versions, batch_size)

            # Process each runtime version in parallel
            all_events = {}

            # Process batches in parallel for each runtime version
            async def process_runtime_version(runtime_version, batches):
                version_events = {}
                for batch in batches:
                    bt.logging.debug(f"Fetching events for runtime version {runtime_version} (batch of {len(batch)} blocks)...")
                    try:
                        events = await self.get_block_events(runtime_version, batch)
                        version_events.update(events)
                    except Exception as e:
                        bt.logging.warning(f"Error fetching events for runtime version {runtime_version}: {e}")
                return version_events

            # Create tasks for each runtime version
            version_tasks = [process_runtime_version(rv, batches) for rv, batches in grouped.items()]
            version_results = await asyncio.gather(*version_tasks)

            # Combine all results
            for result in version_results:
                all_events.update(result)

            # Combine with cached events
            all_events.update(cached_events)

        processing_time = time.time() - start_time
        bt.logging.info(f"All events collected in {processing_time:.2f} seconds. Retrieved {len(all_events)} of {len(block_numbers)} requested blocks.")
        return all_events

async def example():

    import json

    from src.patrol.chain_data.substrate_client import SubstrateClient
    from src.patrol.chain_data.runtime_groupings import load_versions

    network_url = "wss://archive.chain.opentensor.ai:443/"
    versions = load_versions()

    client = SubstrateClient(runtime_mappings=versions, network_url=network_url, max_retries=3)
    await client.initialize()

    fetcher = EventFetcher(substrate_client=client)

    test_cases = [
        [5163655 + i for i in range(1000)],
        # [3804341 + i for i in range(1000)]    # high volume
    ]

    for test_case in test_cases:

        bt.logging.info("Starting next test case.")

        start_time = time.time()
        all_events = await fetcher.fetch_all_events(test_case, 50)
        bt.logging.info(f"\nRetrieved events for {len(all_events)} blocks in {time.time() - start_time:.2f} seconds.")

        with open('raw_event_data.json', 'w') as file:
            json.dump(all_events, file, indent=4)

        # bt.logging.debug(all_events)

if __name__ == "__main__":
    asyncio.run(example())