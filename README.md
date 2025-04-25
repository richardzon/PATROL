# Bittensor Chain Monitor

A focused monitoring bot for Bittensor that tracks important on-chain events and sends notifications to Telegram.

## Features

- **Delegation/Undelegation Monitoring**: Track large stake and unstake events
- **Volume Spike Detection**: Identify significant volume changes in subnets
- **Neuron Registration Tracking**: Monitor for registration bursts on subnets
- **Subnet Ownership Transfer Detection**: Track scheduled coldkey swaps that indicate upcoming subnet ownership changes
- **Intelligent Notification System**: Avoids duplicate notifications and filters out noise
- **Zero-Sum Event Detection**: Identifies and filters out when users delegate and undelegate similar amounts
- **Validator Switch Detection**: Properly identifies when users are switching validators

## Setup

### Prerequisites

- Python 3.8+
- Bittensor
- Telegram Bot Token and Chat ID

### Installation

1. Clone this repository:
```bash
git clone https://github.com/richardzon/bittensor-monitor.git
cd bittensor-monitor
```

2. Install dependencies:
```bash
pip install bittensor requests loguru
```

3. Create a configuration file (`chain_monitor_config.json`):
```json
{
    "telegram_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "YOUR_TELEGRAM_CHAT_ID",
    "taostats_api_key": "YOUR_TAOSTATS_API_KEY",
    "network": "finney",
    "check_interval": 6,
    "volume_interval": 180,
    "history_length": 10,
    "low_volume_threshold": 700,
    "delegation_low_volume": 10,
    "delegation_any_volume": 10,
    "volume_spike_pct": 30,
    "registration_burst": 3,
    "burst_window": 300,
    "exclude_subnet_0": true
}
```

## Usage

### Running the Monitor

```bash
python bittensor_chain_monitor.py
```

### Command-line Options

```bash
python bittensor_chain_monitor.py --config path/to/config.json --network finney --debug
```

### Checking Coldkey Swaps

The monitor logs scheduled coldkey swaps to a file. You can check these with:

```bash
./check_coldkeyswap.py
```

Filter by subnet:
```bash
./check_coldkeyswap.py --subnet 14
```

Show swaps from the last 48 hours:
```bash
./check_coldkeyswap.py --hours 48
```

## Telegram Notifications

The bot sends notifications to Telegram for:

- Large delegation/undelegation events
- Volume spikes in subnets
- Registration bursts on subnets
- Scheduled coldkey swaps (subnet ownership transfers)

## License

MIT
