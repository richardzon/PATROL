import logging
import time
from typing import List, Dict, Tuple, Set, Optional, Any, Callable
import asyncio
import bittensor as bt
from functools import lru_cache
from collections import defaultdict

from bittensor.core.chain_data.utils import decode_account_id
from src.patrol.chain_data.coldkey_finder import ColdkeyFinder

logger = logging.getLogger(__name__)

class EventProcessor:
    def __init__(self, coldkey_finder: ColdkeyFinder):
        """
        Args:
            coldkey_finder: An instance of ColdkeyFinder to resolve coldkey owners.
        """
        self.coldkey_finder = coldkey_finder
        self.semaphore = asyncio.Semaphore(50)  # Increased concurrency
        self._address_cache = {}  # Cache for formatted addresses
        self._event_cache = {}  # Cache for processed events
        self._coldkey_cache = {}  # Cache for coldkey lookups

    def format_address(self, addr: List) -> str:
        """
        Uses Bittensor's decode_account_id to format the given address with caching.
        Assumes 'addr' is provided in the format expected by decode_account_id.
        """
        # Convert to a hashable key for caching
        cache_key = str(addr[0]) if addr and len(addr) > 0 else None

        # Return early if invalid input
        if not cache_key:
            return ""

        # Check cache first
        if cache_key in self._address_cache:
            return self._address_cache[cache_key]

        # Format the address
        try:
            formatted = decode_account_id(addr[0])
            self._address_cache[cache_key] = formatted
            return formatted
        except Exception as e:
            logger.warning(f"Error parsing address from {addr}: {e}")
            # Cache the original value to avoid repeated errors
            self._address_cache[cache_key] = addr[0]
            return addr[0]

    def process_balance_events(self, event: Dict, block_number: int, chain_operations: Dict) -> List[Dict]:
        """
        Process balance events from a block event.
        """
        formatted = []
        if "event" not in event:
            return formatted

        for module, event_list in event["event"].items():
            if module != "Balances":
                continue
            for item in event_list:
                for event_type, details in item.items():
                    if event_type == "Transfer":
                        formatted.append({
                            "coldkey_source": self.format_address(details.get("from")),
                            "coldkey_destination": self.format_address(details.get("to")),
                            "category": "balance",
                            "type": "transfer",
                            "evidence": {
                                "rao_amount": details.get("amount"),
                                "block_number": block_number
                            }
                        })
                    elif event_type == "Withdraw":
                        chain_operations["withdrawal"].append({
                            "coldkey_source": self.format_address(details.get("who")),
                            "rao_amount": details.get("amount")
                        })
                    elif event_type == "Deposit":
                        chain_operations["deposit"].append({
                            "coldkey_destination": self.format_address(details.get("who")),
                            "rao_amount": details.get("amount")
                        })
        return formatted

    async def find_coldkey_with_cache(self, hotkey: str) -> str:
        """Find a coldkey with caching to reduce duplicate lookups."""
        if hotkey in self._coldkey_cache:
            return self._coldkey_cache[hotkey]

        coldkey = await self.coldkey_finder.find(hotkey)
        self._coldkey_cache[hotkey] = coldkey

        # Limit cache size
        if len(self._coldkey_cache) > 10000:
            # Remove oldest entries
            keys_to_remove = list(self._coldkey_cache.keys())[:1000]
            for key in keys_to_remove:
                self._coldkey_cache.pop(key, None)

        return coldkey

    async def process_staking_events(self, event: Dict, block_number: int) -> Tuple[List[Dict], List[Dict]]:
        """
        Process staking events from a block event. Returns two formats:
          - new_format: Detailed staking events.
          - old_format: Events in an older format.
        """
        new_format = []
        old_format = []
        if "event" not in event:
            return new_format, old_format

        for module, event_list in event["event"].items():
            if module != "SubtensorModule":
                continue

            for item in event_list:
                for event_type, details in item.items():
                    if event_type == "StakeAdded":
                        if len(details) == 2:
                            delegate_hotkey = self.format_address(details[0])
                            coldkey_destination = await self.find_coldkey_with_cache(delegate_hotkey)
                            old_format.append({
                                "coldkey_source": None,
                                "coldkey_destination": coldkey_destination,
                                "category": "staking",
                                "type": "add",
                                "evidence": {
                                    "rao_amount": details[1],
                                    "delegate_hotkey_destination": delegate_hotkey,
                                    "block_number": block_number
                                }
                            })
                        elif len(details) >= 5:
                            delegate_hotkey = self.format_address(details[1])
                            coldkey_source = self.format_address(details[0])
                            coldkey_destination = await self.find_coldkey_with_cache(delegate_hotkey)
                            new_format.append({
                                "coldkey_source": coldkey_source,
                                "coldkey_destination": coldkey_destination,
                                "category": "staking",
                                "type": "add",
                                "evidence": {
                                    "rao_amount": details[2],
                                    "delegate_hotkey_destination": delegate_hotkey,
                                    "alpha_amount": details[3],
                                    "destination_net_uid": details[4],
                                    "block_number": block_number
                                }
                            })
                    elif event_type == "StakeRemoved":
                        if len(details) == 2:
                            delegate_hotkey = self.format_address(details[0])
                            old_format.append({
                                "coldkey_destination": None,
                                "coldkey_source": await self.coldkey_finder.find(delegate_hotkey),
                                "category": "staking",
                                "type": "remove",
                                "evidence": {
                                    "rao_amount": details[1],
                                    "delegate_hotkey_source": delegate_hotkey,
                                    "block_number": block_number
                                }
                            })
                        elif len(details) >= 5:
                            delegate_hotkey = self.format_address(details[1])
                            new_format.append({
                                "coldkey_destination": self.format_address(details[0]),
                                "coldkey_source": await self.coldkey_finder.find(delegate_hotkey),
                                "category": "staking",
                                "type": "remove",
                                "evidence": {
                                    "rao_amount": details[2],
                                    "delegate_hotkey_source": delegate_hotkey,
                                    "alpha_amount": details[3],
                                    "source_net_uid": details[4],
                                    "block_number": block_number
                                }
                            })
                    elif event_type == "StakeMoved" and len(details) == 6:
                        source_delegate_hotkey = self.format_address(details[1])
                        destination_delegate_hotkey = self.format_address(details[3])
                        new_format.append({
                            "coldkey_owner": self.format_address(details[0]),
                            "coldkey_source": await self.coldkey_finder.find(source_delegate_hotkey),
                            "coldkey_destination": await self.coldkey_finder.find(destination_delegate_hotkey),
                            "category": "staking",
                            "type": "move",
                            "evidence": {
                                "rao_amount": details[5],
                                "delegate_hotkey_source": source_delegate_hotkey,
                                "delegate_hotkey_destination": destination_delegate_hotkey,
                                "source_net_uid": details[2],
                                "destination_net_uid": details[4],
                                "block_number": block_number
                            }
                        })
        return new_format, old_format

    @staticmethod
    def match_old_stake_events(old_stake_events: List[Dict], chain_operations: Dict) -> List[Dict]:
        """
        Matches old-format staking events with corresponding balance events.
        """
        matched = []
        for entry in old_stake_events:
            if entry["type"] == "add":
                matches = [x for x in chain_operations["withdrawal"]
                           if x["rao_amount"] == entry["evidence"]["rao_amount"]]
                if len(matches) == 1:
                    entry["coldkey_source"] = matches[0]["coldkey_source"]
                    matched.append(entry)
            elif entry["type"] == "remove":
                matches = [x for x in chain_operations["deposit"]
                           if x["rao_amount"] == entry["evidence"]["rao_amount"]]
                if len(matches) == 1:
                    entry["coldkey_destination"] = matches[0]["coldkey_destination"]
                    matched.append(entry)
        return matched

    async def parse_events(self, events: List[Dict], block_number: int, semaphore: asyncio.Semaphore) -> List[Dict]:
        """
        Parses events for a given block with optimized processing.
        """
        # Check cache first
        cache_key = f"block_{block_number}"
        if cache_key in self._event_cache:
            return self._event_cache[cache_key]

        formatted = []
        old_stake_format = []
        chain_operations = {"withdrawal": [], "deposit": []}

        # Process events in batches for better performance
        batch_size = 100
        for i in range(0, len(events), batch_size):
            batch = events[i:i+batch_size]

            # Process balance events first (they're faster and don't need async)
            for event in batch:
                try:
                    # Process balance events and update chain operations
                    formatted.extend(self.process_balance_events(event, block_number, chain_operations))
                except Exception as e:
                    logger.warning(f"Error processing balance event in block {block_number}: {e}")

            # Now process staking events with concurrency control
            staking_tasks = []
            for event in batch:
                staking_tasks.append(self.process_staking_events(event, block_number))

            # Process staking events in parallel with semaphore control
            async with semaphore:
                staking_results = await asyncio.gather(*staking_tasks, return_exceptions=True)

            # Process results
            for result in staking_results:
                if isinstance(result, Exception):
                    logger.warning(f"Error processing staking event in block {block_number}: {result}")
                    continue

                new_stake, old_stake = result
                formatted.extend(new_stake)
                old_stake_format.extend(old_stake)

        # Match old stake events
        try:
            formatted.extend(self.match_old_stake_events(old_stake_format, chain_operations))
        except Exception as e:
            logger.error(f"Error matching old stake events in block {block_number}: {e}")

        # Cache the result
        self._event_cache[cache_key] = formatted

        # Limit cache size
        if len(self._event_cache) > 1000:
            # Remove oldest entries
            keys_to_remove = list(self._event_cache.keys())[:100]
            for key in keys_to_remove:
                self._event_cache.pop(key, None)

        return formatted

    async def process_event_data(self, event_data: dict) -> List[Dict]:
        """
        Processes event data across multiple blocks with optimized parallel processing.
        """
        if not isinstance(event_data, dict):
            logger.error(f"Expected event_data to be a dict, got: {type(event_data)}")
            return []
        if not event_data:
            logger.error("No event data provided.")
            return []

        logger.info(f"Parsing event data from {len(event_data)} blocks.")
        start_time = time.time()

        # Check which blocks we already have in cache
        cached_events = []
        uncached_blocks = {}

        for block_key, block_events in event_data.items():
            try:
                bn = int(block_key)
                cache_key = f"block_{bn}"

                if cache_key in self._event_cache:
                    cached_events.extend(self._event_cache[cache_key])
                elif isinstance(block_events, (list, tuple)):
                    uncached_blocks[bn] = block_events
                else:
                    logger.warning(f"Block {bn} events are not in a tuple or list. Skipping...")
            except ValueError:
                logger.warning(f"Block key {block_key} is not convertible to int. Skipping...")
                continue

        # If all blocks are cached, return immediately
        if not uncached_blocks:
            logger.info(f"All {len(event_data)} blocks found in cache")
            return cached_events

        logger.info(f"Processing {len(uncached_blocks)} uncached blocks out of {len(event_data)} total")

        # Process blocks in batches for better memory management
        batch_size = 20  # Process 20 blocks at a time
        all_parsed_events = list(cached_events)  # Start with cached events

        # Convert to list and sort by block number for more efficient processing
        block_items = sorted(uncached_blocks.items())

        # Process in batches
        for i in range(0, len(block_items), batch_size):
            batch = block_items[i:i+batch_size]

            # Create tasks for this batch
            tasks = [self.parse_events(events, bn, self.semaphore) for bn, events in batch]

            # Process batch
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect results
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Error parsing block {batch[j][0]}: {result}")
                else:
                    all_parsed_events.extend(result)

            # Log progress for large batches
            if len(block_items) > 100 and (i + batch_size) % 100 == 0:
                progress = min(100, int((i + batch_size) / len(block_items) * 100))
                logger.info(f"Processing progress: {progress}% complete")

        processing_time = time.time() - start_time
        logger.info(f"Processed {len(all_parsed_events)} events from {len(event_data)} blocks in {processing_time:.2f} seconds.")
        return all_parsed_events

if __name__ == "__main__":

    import json
    from src.patrol.chain_data.substrate_client import SubstrateClient
    from src.patrol.chain_data.runtime_groupings import load_versions

    network_url = "wss://archive.chain.opentensor.ai:443/"
    versions = load_versions()

    async def example():

        bt.debug()

        file_path = "raw_event_data.json"  # you will need to create this by running event_fetcher and saving the output.
        with open(file_path, "r") as f:
            data = json.load(f)

        client = SubstrateClient(runtime_mappings=versions, network_url=network_url, max_retries=3)
        await client.initialize()

        coldkey_finder = ColdkeyFinder(substrate_client=client)

        event_processor = EventProcessor(coldkey_finder=coldkey_finder)

        parsed_events = await event_processor.process_event_data(data)
        logger.info(parsed_events)

    asyncio.run(example())