
class Constants:
    # Scoring parameters
    RESPONSE_TIME_HALF_SCORE: int = 2  # Time in seconds at which response time score is 0.5
    INFLECTION_POINT = 1000  # Inflection point for sigmoid function used in scoring
    STEEPNESS = 0.005  # Steepness of sigmoid function used in scoring
    U64_MAX = 2**64 - 1  # Maximum value for u64

    # Block limits
    LOWER_BLOCK_LIMIT: int = 3014341  # Lower limit for block numbers
    MAX_RESPONSE_TIME: int = 12  # Maximum response time in seconds

    # Performance optimization parameters
    DEFAULT_MAX_FUTURE_EVENTS: int = 150  # Default number of blocks to search ahead
    DEFAULT_MAX_PAST_EVENTS: int = 150  # Default number of blocks to search behind
    DEFAULT_EVENT_BATCH_SIZE: int = 75  # Default number of blocks to query at once
    DEFAULT_TIMEOUT: int = 15  # Default timeout for operations in seconds
    DEFAULT_MAX_WORKERS: int = 8  # Default number of worker threads

    # Cache sizes
    MAX_EVENT_CACHE_SIZE: int = 10000  # Maximum number of events to cache
    MAX_BLOCK_HASH_CACHE_SIZE: int = 10000  # Maximum number of block hashes to cache
    MAX_SUBGRAPH_CACHE_SIZE: int = 100  # Maximum number of subgraphs to cache
    MAX_COLDKEY_CACHE_SIZE: int = 10000  # Maximum number of coldkeys to cache

    # Connection parameters
    MAX_RETRIES: int = 5  # Maximum number of retries for network operations
    RETRY_DELAY: int = 1  # Delay between retries in seconds
    MAX_CONCURRENT_REQUESTS: int = 20  # Maximum number of concurrent requests
