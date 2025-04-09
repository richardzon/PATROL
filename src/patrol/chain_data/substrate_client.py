import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from functools import lru_cache

import bittensor as bt

from async_substrate_interface import AsyncSubstrateInterface
from async_substrate_interface.async_substrate import Websocket

from src.patrol.constants import Constants

class CustomAsyncSubstrateInterface(AsyncSubstrateInterface):
    def __init__(self, url=None, ws=None, **kwargs):
        """
        Extends AsyncSubstrateInterface to allow injecting a custom websocket connection.

        Args:
            url: the URI of the chain to connect to.
            ws: Optional websocket connection to use. If provided, it overrides the default one.
            **kwargs: any additional keyword arguments for the parent class.
        """
        # Initialize the parent class with all normal parameters.
        super().__init__(url, **kwargs)
        # Override the websocket connection if one is provided.
        self.ws = ws

class SubstrateClient:
    def __init__(self, runtime_mappings: dict, network_url: str, websocket: Websocket = None,
                 keepalive_interval: int = 20, max_retries: int = Constants.MAX_RETRIES):
        """
        Args:
            runtime_mappings: A dict mapping group_id to runtime versions.
            network_url: The URL for the archive node.
            keepalive_interval: Interval for keepalive pings in seconds.
            max_retries: Number of times to retry a query before reinitializing the connection.
        """
        self.runtime_mappings = runtime_mappings
        self.keepalive_interval = keepalive_interval
        self.max_retries = max_retries
        self.websocket = websocket
        self.substrate_cache = {}  # group_id -> AsyncSubstrateInterface
        self.network_url = network_url
        self.query_cache = {}  # Cache for query results
        self.last_connection_check = 0
        self.connection_check_interval = 60  # Check connection every 60 seconds

    async def initialize(self):
        """
        Initializes the websocket connection and loads metadata instances for all runtime versions.
        Optimized with better connection handling and parallel initialization.
        """
        bt.logging.info("Initializing websocket connection.")
        if self.websocket is None:
            self.websocket = Websocket(
                    self.network_url,
                    options={
                        "max_size": 2**32,
                        "write_limit": 2**16,
                        "max_queue": 1024,  # Increased queue size
                        "timeout": 60.0,     # Increased timeout
                    },
                )

        # Connect with retry logic
        max_connect_retries = 5
        for attempt in range(max_connect_retries):
            try:
                await self.websocket.connect(force=True)
                self.last_connection_check = time.time()
                break
            except Exception as e:
                bt.logging.warning(f"Connection attempt {attempt+1} failed: {e}")
                if attempt < max_connect_retries - 1:
                    await asyncio.sleep(Constants.RETRY_DELAY * (attempt + 1))
                else:
                    raise Exception(f"Failed to connect after {max_connect_retries} attempts")

        # Initialize substrate instances in parallel
        initialization_tasks = []
        for version, mapping in self.runtime_mappings.items():
            initialization_tasks.append(self._initialize_substrate_instance(int(version), mapping))

        # Wait for all initializations to complete
        await asyncio.gather(*initialization_tasks)

        bt.logging.info(f"Substrate client successfully initialized with {len(self.substrate_cache)} runtime versions.")

    async def _initialize_substrate_instance(self, version: int, mapping: Dict):
        """Helper method to initialize a single substrate instance"""
        bt.logging.info(f"Initializing substrate instance for version: {version}.")
        try:
            substrate = CustomAsyncSubstrateInterface(ws=self.websocket)
            await substrate.init_runtime(block_hash=mapping["block_hash_min"])
            self.substrate_cache[version] = substrate
            bt.logging.info(f"Successfully initialized substrate instance for version: {version}.")
        except Exception as e:
            bt.logging.error(f"Failed to initialize substrate instance for version {version}: {e}")
            raise

    async def _reinitialize_connection(self):
        """
        Reinitializes the websocket connection with improved error handling.
        """
        bt.logging.info("Reinitializing websocket connection...")
        try:
            if self.websocket:
                await self.websocket.shutdown()
        except Exception as e:
            bt.logging.warning(f"Error during websocket shutdown: {e}")

        self.websocket = Websocket(
                self.network_url,
                options={
                    "max_size": 2**32,
                    "write_limit": 2**16,
                    "max_queue": 1024,  # Increased queue size
                    "timeout": 60.0,     # Increased timeout
                },
            )

        # Connect with retry logic
        max_connect_retries = 5
        for attempt in range(max_connect_retries):
            try:
                await self.websocket.connect(force=True)
                self.last_connection_check = time.time()
                bt.logging.info("Successfully reinitialized websocket connection.")
                return
            except Exception as e:
                bt.logging.warning(f"Reinitialization attempt {attempt+1} failed: {e}")
                if attempt < max_connect_retries - 1:
                    await asyncio.sleep(Constants.RETRY_DELAY * (attempt + 1))

        bt.logging.error("Failed to reinitialize websocket connection after multiple attempts.")
        raise Exception("Failed to reinitialize connection")

    async def _check_connection(self):
        """Check if the connection is still alive and reconnect if needed"""
        current_time = time.time()
        if current_time - self.last_connection_check > self.connection_check_interval:
            self.last_connection_check = current_time
            try:
                # Simple ping to check connection
                if not self.websocket.connected:
                    bt.logging.warning("Connection lost, reinitializing...")
                    await self._reinitialize_connection()
            except Exception as e:
                bt.logging.warning(f"Connection check failed: {e}")
                await self._reinitialize_connection()

    async def query(self, method_name: str, runtime_version: int = None, *args, **kwargs):
        """
        Executes a query using the substrate instance for the given runtime version.
        Optimized with caching, better error handling, and connection management.

        Args:
            runtime_version: The runtime version for the substrate instance.
            method_name: The name of the substrate method to call (e.g., "get_block_hash").
            *args, **kwargs: Arguments for the query method.

        Returns:
            The result of the query method.
        """
        # Check connection periodically
        await self._check_connection()

        # Determine runtime version
        if runtime_version is None:
            bt.logging.debug("No runtime version provided, setting default.")
            runtime_version = max(self.substrate_cache.keys())

        if runtime_version not in self.substrate_cache:
            raise Exception(f"Runtime version {runtime_version} is not initialized. Available versions: {list(self.substrate_cache.keys())}")

        # Check if we can use cache for this query
        cacheable_methods = ["get_block_hash", "get_block", "_preprocess"]
        if method_name in cacheable_methods:
            # Create a cache key from the method name and arguments
            cache_key = (method_name, runtime_version, str(args), str(kwargs))
            if cache_key in self.query_cache:
                return self.query_cache[cache_key]

        # Execute query with retries
        errors = []
        for attempt in range(self.max_retries):
            try:
                substrate = self.substrate_cache[runtime_version]
                query_func = getattr(substrate, method_name)
                result = await query_func(*args, **kwargs)

                # Cache the result if it's a cacheable method
                if method_name in cacheable_methods:
                    self.query_cache[cache_key] = result

                    # Limit cache size
                    if len(self.query_cache) > Constants.MAX_EVENT_CACHE_SIZE:
                        # Remove oldest entries (first 10%)
                        keys_to_remove = list(self.query_cache.keys())[:int(Constants.MAX_EVENT_CACHE_SIZE * 0.1)]
                        for key in keys_to_remove:
                            self.query_cache.pop(key, None)

                return result

            except Exception as e:
                errors.append(e)
                bt.logging.warning(f"Query error on version {runtime_version} attempt {attempt + 1}: {e}")

                # Handle rate limiting with exponential backoff
                if "429" in str(e):
                    backoff_time = 2 * (attempt + 1)
                    bt.logging.warning(f"Rate limited. Backing off for {backoff_time} seconds.")
                    await asyncio.sleep(backoff_time)
                else:
                    # For other errors, use a shorter delay
                    await asyncio.sleep(Constants.RETRY_DELAY * (attempt + 1))

                    # Try to reinitialize connection on the second-to-last attempt
                    if attempt == self.max_retries - 2:
                        await self._reinitialize_connection()

        # If we get here, all retries failed
        error_msg = f"Query failed for version {runtime_version} after {self.max_retries} attempts. Errors: {errors}"
        bt.logging.error(error_msg)
        raise Exception(error_msg)

    def return_runtime_versions(self):
        return self.runtime_mappings

if __name__ == "__main__":

    from src.patrol.chain_data.runtime_groupings import load_versions, get_version_for_block

    async def example():

        # Replace with your actual substrate node WebSocket URL.
        network_url = "wss://archive.chain.opentensor.ai:443/"
        versions = load_versions()

        # shortening the version dict for dev

        keys_to_keep = {"149", "150", "151"}
        versions = {k: versions[k] for k in keys_to_keep if k in versions}

        # Create an instance of SubstrateClient with a shorter keepalive interval.
        client = SubstrateClient(runtime_mappings=versions, network_url=network_url, max_retries=3)

        # Initialize substrate connections for all groups.
        await client.initialize()

        version = get_version_for_block(3157275, 5400000, versions)
        version = None
        block_hash = await client.query("get_block_hash", version, 3157275)

        await client.websocket.shutdown()

        block_hash = await client.query("get_block_hash", version, 3157275)
        bt.logging.info(block_hash)

    asyncio.run(example())