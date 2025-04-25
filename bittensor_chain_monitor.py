#!/usr/bin/env python3
# bittensor_chain_monitor.py - A focused monitoring bot for Bittensor
# Monitors delegation events, volume spikes, registrations, and subnet ownership changes

import asyncio
import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional, Any

import bittensor as bt
import requests
from loguru import logger

# Default configuration
DEFAULT_CONFIG = {
    # Credentials
    "telegram_token": "8100636692:AAF35dWvzadLYKBk9DjDcXeH5V91Ny2HnXQ",
    "telegram_chat_id": "6791510426",
    "taostats_api_key": "tao-5ea1c271-c011-4f86-90e8-c505c8e6da11:be28c1cf",
    "network": "finney",  # Bittensor network

    # Timing
    "check_interval": 6,          # seconds between new-block polls
    "volume_interval": 180,       # seconds between taostats volume fetches (3m)
    "history_length": 10,         # keep the last 10 volume snapshots (~30m)

    # Thresholds
    "low_volume_threshold": 700,  # TAO / 24h to classify subnet as low volume
    "delegation_low_volume": 10,  # TAO delegations on low-volume subnet alert
    "delegation_any_volume": 10,  # TAO delegations on any subnet alert (changed from 20 to 10)
    "volume_spike_pct": 30,       # % increase vs avg to count as spike
    "registration_burst": 3,      # N registrations in burst_window to alert
    "burst_window": 300,          # seconds for registration burst window (5m)

    # Misc
    "debug": False,
    "exclude_subnet_0": True,     # Exclude subnet 0 from monitoring
}

def nano_to_tao(nano: int) -> float:
    """Convert nano TAO (rao) to TAO"""
    return nano / 1_000_000_000

def tao_to_nano(tao: float) -> int:
    """Convert TAO to nano TAO (rao)"""
    return int(tao * 1_000_000_000)

class BittensorChainMonitor:
    """Monitor for Bittensor chain events with focus on delegations, volume, registrations, and ownership"""

    def __init__(self, config: Dict = None):
        """Initialize the monitor with configuration"""
        self.config = config or DEFAULT_CONFIG
        self.running = False

        # State tracking
        self.current_block = 0
        self.last_checked_block = 0
        self.subnet_volumes = {}  # netuid -> nano TAO/24h
        self.volume_history = deque(maxlen=self.config["history_length"])
        self.liquidity_history = deque(maxlen=self.config["history_length"])
        self.last_volume_check = 0
        self.subnet_owners = {}  # netuid -> owner address
        self.last_subnet_owners_refresh = 0  # Last time subnet owners were refreshed
        self.subnet_owners_refresh_interval = 3600  # Refresh subnet owners every hour (in seconds)

        # Track last sent volume changes to avoid duplicates
        self.last_volume_changes = []
        self.last_volume_notification_time = 0

        # Event deduplication
        self.seen_events = {}  # event_id -> timestamp

        # Enhanced event deduplication for delegation events
        self.event_fingerprints = {}  # fingerprint -> {timestamp, event_id, count}

        # Cooldown tracking for subnets
        self.subnet_action_cooldowns = {}  # (netuid, action, amount_rounded) -> timestamp

        # Notification deduplication
        self.sent_notifications = {}  # notification_fingerprint -> timestamp
        self.notification_cooldown = 1800  # 30 minutes cooldown for similar notifications

        # Registration tracking per subnet: deque of timestamps
        self.registrations = defaultdict(lambda: deque(maxlen=100))

        # Track related delegation events (for detecting validator switches)
        self.recent_delegation_events = {}  # (coldkey, netuid) -> {action, amount, timestamp, event_id}

        # Track subnet-level delegation events (for detecting zero-sum events)
        self.subnet_delegation_events = {}  # netuid -> list of {coldkey, action, amount, timestamp, event_id}

        # API rate limiting
        self.api_call_times = []  # List of timestamps for API calls

        # Configure logging
        logger.remove()
        log_level = "DEBUG" if self.config.get("debug", False) else "INFO"
        logger.add(
            lambda msg: print(msg),
            level=log_level,
            colorize=True,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        logger.add(
            "bittensor_monitor.log",
            rotation="10 MB",
            retention="1 week",
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
        )

        logger.info("Bittensor Chain Monitor initialized")

    def check_notification_fingerprint(self, message: str) -> bool:
        """
        Check if we've sent a similar notification recently

        Args:
            message: The notification message

        Returns:
            bool: True if this is a new notification that should be sent, False if it's in cooldown
        """
        # Create a simplified fingerprint by removing variable parts
        # Remove block numbers, timestamps, and exact amounts
        simplified = re.sub(r'Block: \d+', 'Block: XXX', message)
        simplified = re.sub(r'\d+\.\d+ TAO', 'XX.XX TAO', simplified)
        simplified = re.sub(r'\d+% of daily volume', 'XX% of daily volume', simplified)

        # Create a hash of the simplified message as the fingerprint
        fingerprint = hashlib.md5(simplified.encode()).hexdigest()

        # Check if we've sent a similar notification recently
        current_time = time.time()

        if fingerprint in self.sent_notifications:
            last_time = self.sent_notifications[fingerprint]
            time_diff = current_time - last_time

            if time_diff < self.notification_cooldown:
                logger.info(f"Notification in cooldown: last sent {time_diff:.1f} seconds ago")
                return False

        # Update notification timestamp
        self.sent_notifications[fingerprint] = current_time

        # Clean up old notifications (older than 2 hours)
        self.sent_notifications = {k: v for k, v in self.sent_notifications.items()
                                  if current_time - v < 7200}

        return True

    def send_telegram_message(self, message: str, html: bool = True, bypass_cooldown: bool = False) -> bool:
        """Send a message to Telegram

        Args:
            message: The message to send
            html: Whether to use HTML formatting (default: True)
            bypass_cooldown: Whether to bypass the notification cooldown check (default: False)

        Returns:
            bool: True if the message was sent successfully, False otherwise
        """
        try:
            # Check for duplicate notifications unless bypassing cooldown
            if not bypass_cooldown and not self.check_notification_fingerprint(message):
                logger.info("Skipping duplicate notification (in cooldown)")
                return False

            token = self.config.get("telegram_token")
            chat_id = self.config.get("telegram_chat_id")

            if not token or not chat_id:
                logger.warning("Telegram credentials not configured. Skipping notification.")
                logger.info(f"Would have sent: {message}")
                return False

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML" if html else "Markdown",
                "disable_web_page_preview": True
            }

            response = requests.post(url, data=data, timeout=10)

            if response.status_code == 200:
                logger.info("Telegram notification sent successfully")
                return True
            else:
                logger.error(f"Failed to send Telegram notification: {response.text}")
                # If HTML fails, try with plain text (remove HTML tags)
                if html:
                    logger.info("Retrying without HTML parse mode")
                    # Simple HTML tag removal for fallback
                    plain_message = message.replace("<b>", "").replace("</b>", "")
                    plain_message = plain_message.replace("<code>", "").replace("</code>", "")
                    plain_message = plain_message.replace("<i>", "").replace("</i>", "")
                    return self.send_telegram_message(plain_message, html=False, bypass_cooldown=True)
                return False
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {str(e)}")
            return False

    def check_event_fingerprint(self, netuid, action, amount, cooldown_seconds=300):
        """
        Check if we've seen a similar event recently and should skip it

        Args:
            netuid: The subnet ID
            action: The action type (delegate, undelegate, validator_switch)
            amount: The amount in TAO
            cooldown_seconds: Cooldown period in seconds (default: 5 minutes)

        Returns:
            bool: True if this is a new event that should be processed, False if it's in cooldown
        """
        # Round amount to 2 decimal places to group similar amounts
        amount_rounded = round(amount, 2)

        # Create a fingerprint for this event
        fingerprint = f"{netuid}_{action}_{amount_rounded}"

        # Check subnet action cooldown
        cooldown_key = (netuid, action, amount_rounded)
        current_time = time.time()

        if cooldown_key in self.subnet_action_cooldowns:
            last_time = self.subnet_action_cooldowns[cooldown_key]
            time_diff = current_time - last_time

            if time_diff < cooldown_seconds:
                logger.info(f"  Event in cooldown: {fingerprint} (last seen {time_diff:.1f} seconds ago)")
                return False

        # Update cooldown timestamp
        self.subnet_action_cooldowns[cooldown_key] = current_time

        # Track fingerprint
        if fingerprint in self.event_fingerprints:
            # Update existing fingerprint
            self.event_fingerprints[fingerprint]["timestamp"] = current_time
            self.event_fingerprints[fingerprint]["count"] += 1
            logger.info(f"  Updated fingerprint: {fingerprint} (seen {self.event_fingerprints[fingerprint]['count']} times)")
        else:
            # Create new fingerprint
            self.event_fingerprints[fingerprint] = {
                "timestamp": current_time,
                "count": 1
            }
            logger.info(f"  New fingerprint: {fingerprint}")

        # Clean up old fingerprints (older than 1 hour)
        self.event_fingerprints = {k: v for k, v in self.event_fingerprints.items()
                                  if current_time - v["timestamp"] < 3600}

        return True

    def get_alpha_name_for_subnet(self, netuid: int) -> str:
        """Get the alpha token name for a subnet"""
        # Map of known subnet IDs to their alpha token names
        subnet_names = {
            1: "alpha",
            2: "beta",
            3: "gamma",
            4: "delta",
            5: "epsilon",
            6: "zeta",
            7: "eta",
            8: "theta",
            9: "iota",
            10: "kappa",
            11: "lambda",
            12: "mu",
            13: "nu",
            14: "xi",
            15: "omicron",
            16: "pi",
            17: "rho",
            18: "sigma",
            19: "tau",
            20: "upsilon",
            21: "phi",
            22: "chi",
            23: "psi",
            24: "omega"
        }

        # Return the name if known, otherwise use a generic name
        return subnet_names.get(netuid, f"subnet{netuid}")

    async def check_api_rate_limit(self):
        """Check and enforce API rate limit (60 calls per minute)"""
        current_time = time.time()

        # Remove API calls older than 1 minute
        self.api_call_times = [t for t in self.api_call_times if current_time - t < 60]

        # Check if we're at the rate limit
        if len(self.api_call_times) >= 60:
            # Calculate time to wait
            oldest_call = min(self.api_call_times)
            wait_time = 60 - (current_time - oldest_call) + 1  # Add 1 second buffer

            logger.warning(f"API rate limit reached. Waiting {wait_time:.2f} seconds before next call.")
            await asyncio.sleep(wait_time)

            # Recursive call to check again after waiting
            await self.check_api_rate_limit()

        # Record this API call
        self.api_call_times.append(current_time)

    async def fetch_subnet_volumes(self):
        """Fetch volume and liquidity data for all subnets from TaoStats API"""
        try:
            # Check if it's time to update volume data
            current_time = time.time()
            if current_time - self.last_volume_check < self.config["volume_interval"]:
                return  # Not time to check yet

            # Check API rate limit before making the call
            await self.check_api_rate_limit()

            # Get subnet pools data which contains volume and liquidity information
            url = "https://api.taostats.io/api/dtao/pool/latest/v1"
            headers = {
                "accept": "application/json",
                "Authorization": self.config["taostats_api_key"]
            }

            logger.info(f"Fetching subnet data from {url}")
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()

                # Verify we have valid data
                if not data or "data" not in data:
                    logger.warning(f"Invalid or empty response from subnet API: {data}")
                    return False

                # Log the response structure for debugging
                logger.debug(f"Received data with {len(data.get('data', []))} entries")
                if data.get('data') and len(data.get('data')) > 0:
                    logger.debug(f"First subnet data structure: {json.dumps(data['data'][0], indent=2)}")

                # Process the data
                volume_snapshot = {}  # Current volume snapshot
                liquidity_snapshot = {}  # Current liquidity snapshot
                low_volume_subnets = []
                high_volume_subnets = []
                volume_threshold = self.config["low_volume_threshold"]

                for subnet in data.get("data", []):
                    try:
                        netuid = subnet.get("netuid")
                        if netuid is None:
                            continue

                        # Convert netuid to int if it's a string
                        if isinstance(netuid, str):
                            netuid = int(netuid)

                        # Skip subnet 0 if configured to do so
                        if netuid == 0 and self.config.get("exclude_subnet_0", True):
                            continue

                        # Get volume in nano TAO (rao)
                        volume_nano = float(subnet.get("tao_volume_24_hr", 0))

                        # Get liquidity in TAO (already in TAO format)
                        liquidity_tao = float(subnet.get("liquidity", 0))
                        if liquidity_tao > 1e20:  # Handle extremely large values that might be in rao
                            liquidity_tao = nano_to_tao(liquidity_tao)

                        # Store the volume and liquidity
                        volume_snapshot[netuid] = volume_nano
                        liquidity_snapshot[netuid] = liquidity_tao

                        # Check if this is a low or high volume subnet
                        volume_tao = nano_to_tao(volume_nano)
                        if volume_tao < volume_threshold:
                            low_volume_subnets.append(netuid)
                        else:
                            high_volume_subnets.append(netuid)

                    except Exception as e:
                        logger.error(f"Error processing subnet data: {str(e)}")

                # Check if we have previous data to compare
                previous_volume = None
                previous_liquidity = None

                if self.volume_history and len(self.volume_history) > 0:
                    previous_volume = self.volume_history[-1]

                if self.liquidity_history and len(self.liquidity_history) > 0:
                    previous_liquidity = self.liquidity_history[-1]

                # Log sample changes for a few subnets
                sample_subnets = list(volume_snapshot.keys())[:5]  # Take first 5 subnets as sample

                if previous_volume:
                    logger.info("Sample volume changes since last update:")
                    for netuid in sample_subnets:
                        if netuid in previous_volume:
                            prev_vol = nano_to_tao(previous_volume[netuid])
                            curr_vol = nano_to_tao(volume_snapshot[netuid])
                            pct_change = 0
                            if prev_vol > 0:
                                pct_change = ((curr_vol - prev_vol) / prev_vol) * 100
                            logger.info(f"  Subnet {netuid}: {prev_vol:.2f} → {curr_vol:.2f} TAO ({pct_change:.2f}%)")

                if previous_liquidity:
                    logger.info("Sample liquidity changes since last update:")
                    for netuid in sample_subnets:
                        if netuid in previous_liquidity:
                            prev_liq = previous_liquidity[netuid]
                            curr_liq = liquidity_snapshot[netuid]
                            pct_change = 0
                            if prev_liq > 0:
                                pct_change = ((curr_liq - prev_liq) / prev_liq) * 100
                            logger.info(f"  Subnet {netuid}: {prev_liq:.2f} → {curr_liq:.2f} TAO ({pct_change:.2f}%)")

                # Update state
                self.subnet_volumes = volume_snapshot
                self.volume_history.append(volume_snapshot)
                self.liquidity_history.append(liquidity_snapshot)
                self.last_volume_check = current_time

                # Log summary
                logger.info(f"Fetched data for {len(volume_snapshot)} subnets")
                logger.info(f"Low volume subnets (<{volume_threshold} TAO): {len(low_volume_subnets)} subnets")
                logger.info(f"High volume subnets (≥{volume_threshold} TAO): {len(high_volume_subnets)} subnets")

                # Log a few example volumes for verification
                if volume_snapshot:
                    # Get top 3 subnets by volume (excluding subnet 0)
                    top_volumes = []
                    for netuid, volume in volume_snapshot.items():
                        if netuid == 0:
                            continue
                        top_volumes.append((netuid, volume))

                    top_volumes.sort(key=lambda x: x[1], reverse=True)
                    top_3 = top_volumes[:3]

                    logger.info("Top 3 subnets by volume:")
                    for netuid, volume in top_3:
                        logger.info(f"  Subnet {netuid}: {nano_to_tao(volume):.2f} TAO")

                # Log a few example liquidities for verification
                if liquidity_snapshot:
                    # Get top 3 subnets by liquidity (excluding subnet 0)
                    top_liquidity = []
                    for netuid, liquidity in liquidity_snapshot.items():
                        if netuid == 0:
                            continue
                        top_liquidity.append((netuid, liquidity))

                    top_liquidity.sort(key=lambda x: x[1], reverse=True)
                    top_3 = top_liquidity[:3]

                    logger.info("Top 3 subnets by liquidity:")
                    for netuid, liquidity in top_3:
                        logger.info(f"  Subnet {netuid}: {liquidity:.2f} TAO")

                # Log that we're checking for spikes
                logger.info("Checking for volume and liquidity spikes...")

                return True
            else:
                logger.warning(f"Failed to get subnet data: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error fetching subnet data: {str(e)}")
            return False

    async def detect_volume_spikes(self):  # Only detecting volume spikes now, not liquidity
        """Detect volume spikes by comparing current data to the previous snapshot"""
        if len(self.volume_history) < 2:
            logger.info("Not enough volume history to detect spikes yet (need at least 2 snapshots)")
            return  # Need at least 2 snapshots to detect spikes

        try:
            # Get the latest snapshots
            latest_volume = self.volume_history[-1]
            latest_liquidity = self.liquidity_history[-1]

            # Get the previous snapshots
            previous_volume = self.volume_history[-2]
            previous_liquidity = self.liquidity_history[-2]

            # Log the number of subnets in each snapshot
            logger.info(f"Checking volume spikes: Latest snapshot has {len(latest_volume)} subnets, previous has {len(previous_volume)} subnets")
            logger.info(f"Current spike threshold: {self.config['volume_spike_pct']}%")

            # Find subnets with spikes
            volume_spikes = []
            significant_volume_changes = []  # Track changes that are notable but below threshold

            # Log the top changes for visibility
            all_volume_changes = []

            # Process volume changes
            for netuid, current_volume in latest_volume.items():
                # Skip if not in previous snapshot
                if netuid not in previous_volume:
                    logger.debug(f"Subnet {netuid} not in previous volume snapshot, skipping")
                    continue

                # Get previous volume
                prev_volume = previous_volume[netuid]

                # Skip if previous volume is zero to avoid division by zero
                if prev_volume == 0:
                    logger.debug(f"Subnet {netuid} had zero previous volume, skipping")
                    continue

                # Calculate percentage change
                percent_change = ((current_volume - prev_volume) / prev_volume) * 100

                # Only track significant volumes (> 1 TAO)
                current_volume_tao = nano_to_tao(current_volume)
                prev_volume_tao = nano_to_tao(prev_volume)

                if current_volume_tao > 1:
                    all_volume_changes.append({
                        "netuid": netuid,
                        "current_volume": current_volume_tao,
                        "previous_volume": prev_volume_tao,
                        "percent_change": percent_change
                    })

                # Check if the change exceeds the threshold
                if percent_change >= self.config["volume_spike_pct"]:
                    # Only consider significant volume (> 1 TAO)
                    if current_volume_tao > 1:
                        logger.info(f"Volume spike detected for subnet {netuid}: {percent_change:.2f}% increase ({prev_volume_tao:.2f} → {current_volume_tao:.2f} TAO)")
                        volume_spikes.append({
                            "netuid": netuid,
                            "current_volume": current_volume,
                            "previous_volume": prev_volume,
                            "percent_change": percent_change
                        })
                # Track notable changes (> 5%) for logging
                elif percent_change >= 5 and current_volume_tao > 1:
                    significant_volume_changes.append({
                        "netuid": netuid,
                        "current_volume_tao": current_volume_tao,
                        "previous_volume_tao": prev_volume_tao,
                        "percent_change": percent_change
                    })

            # Liquidity processing removed as requested - focusing only on volume
            logger.debug("Skipping liquidity change processing (focusing on volume only)")

            # Log the top volume changes for visibility
            if all_volume_changes:
                # Sort by absolute percent change (highest first)
                all_volume_changes.sort(key=lambda x: abs(x["percent_change"]), reverse=True)

                logger.info(f"Top 5 volume changes in this update:")
                for change in all_volume_changes[:5]:
                    netuid = change["netuid"]
                    alpha_name = self.get_alpha_name_for_subnet(netuid)
                    logger.info(f"  Subnet {netuid} ({alpha_name.upper()}): {change['previous_volume']:.2f} → {change['current_volume']:.2f} TAO ({change['percent_change']:.2f}%)")

                # Send a notification with top 3 volume changes
                if len(all_volume_changes) >= 3:
                    # Create message for top 3 volume changes
                    message = "📊 <b>TOP VOLUME CHANGES</b>\n\n"
                    message += f"Comparing latest volume snapshots:\n\n"

                    for i, change in enumerate(all_volume_changes[:3]):
                        netuid = change["netuid"]
                        alpha_name = self.get_alpha_name_for_subnet(netuid)
                        message += f"<b>{i+1}. Subnet {netuid}</b> ({alpha_name.upper()}):\n"
                        message += f"• {change['previous_volume']:.2f} → {change['current_volume']:.2f} TAO "

                        # Add arrow indicator based on direction of change
                        if change["percent_change"] > 0:
                            message += f"(↑ {change['percent_change']:.2f}%)\n\n"
                        elif change["percent_change"] < 0:
                            message += f"(↓ {change['percent_change']:.2f}%)\n\n"
                        else:
                            message += f"(0.00%)\n\n"

                    # Only send if there are actual changes (at least one non-zero percent change)
                    has_changes = any(abs(change["percent_change"]) > 0.01 for change in all_volume_changes[:3])

                    # Check if these changes are the same as the last ones we sent
                    current_time = time.time()
                    is_duplicate = False

                    # Create a simplified representation of the changes for comparison
                    current_changes = [
                        (change["netuid"], round(change["previous_volume"], 2), round(change["current_volume"], 2), round(change["percent_change"], 2))
                        for change in all_volume_changes[:3]
                    ]

                    # Check if this is the same as the last notification we sent
                    if self.last_volume_changes and current_changes == self.last_volume_changes:
                        # Only consider it a duplicate if it was sent recently (within 10 minutes)
                        if current_time - self.last_volume_notification_time < 600:  # 10 minutes
                            is_duplicate = True
                            logger.info("Skipping duplicate volume changes notification (same as previous)")

                    if has_changes and not is_duplicate:
                        logger.info("Sending top 3 volume changes notification")
                        self.send_telegram_message(message)

                        # Update the last sent changes and timestamp
                        self.last_volume_changes = current_changes
                        self.last_volume_notification_time = current_time
                    elif not has_changes:
                        logger.info("Skipping top 3 volume changes notification (no significant changes)")

            # Liquidity change logging removed as requested - focusing only on volume
            logger.debug("Skipping liquidity change logging (focusing on volume only)")

            # Log significant but below-threshold volume changes
            if significant_volume_changes and not volume_spikes:
                logger.info(f"Found {len(significant_volume_changes)} notable volume changes (>5%) but below the {self.config['volume_spike_pct']}% threshold:")
                for change in significant_volume_changes[:3]:  # Show top 3
                    netuid = change["netuid"]
                    alpha_name = self.get_alpha_name_for_subnet(netuid)
                    logger.info(f"  Subnet {netuid} ({alpha_name.upper()}): {change['previous_volume_tao']:.2f} → {change['current_volume_tao']:.2f} TAO ({change['percent_change']:.2f}%)")

            # Significant liquidity change logging removed as requested - focusing only on volume
            logger.debug("Skipping significant liquidity change logging (focusing on volume only)")

            # If we found volume spikes, send a notification
            if volume_spikes:
                # Sort by percent change (highest first)
                volume_spikes.sort(key=lambda x: x["percent_change"], reverse=True)

                logger.info(f"Found {len(volume_spikes)} volume spikes above {self.config['volume_spike_pct']}% threshold")

                # Create message
                message = "📈 <b>VOLUME SPIKE DETECTED!</b>\n\n"

                # Add details for each spike (limit to top 5)
                for spike in volume_spikes[:5]:
                    netuid = spike["netuid"]
                    current_volume_tao = nano_to_tao(spike["current_volume"])
                    previous_volume_tao = nano_to_tao(spike["previous_volume"])
                    percent_change = spike["percent_change"]

                    # Get alpha token name
                    alpha_name = self.get_alpha_name_for_subnet(netuid)

                    message += f"Subnet <b>{netuid}</b> ({alpha_name.upper()}):\n"
                    message += f"• Current Volume: <b>{current_volume_tao:.2f} TAO</b> (↑ {percent_change:.1f}%)\n"
                    message += f"• Previous Volume: {previous_volume_tao:.2f} TAO\n\n"

                # Add trading tip
                message += "💡 <b>Trading Tip:</b> Volume spikes often precede price movements."

                # Send the Telegram notification
                self.send_telegram_message(message)
                logger.info(f"Volume spike notification sent for {len(volume_spikes)} subnets")
            else:
                logger.info("No volume spikes detected above threshold")

            # Liquidity spike notification removed as requested
            logger.info("Skipping liquidity spike detection (focusing on volume only)")

            # Test spike notification removed as requested

        except Exception as e:
            logger.error(f"Error detecting spikes: {str(e)}")

    async def monitor_delegation_events(self):
        """Monitor delegation and undelegation events"""
        try:
            # Check API rate limit before making the call
            await self.check_api_rate_limit()

            # Get delegation events from TaoStats API
            url = "https://api.taostats.io/api/delegation/v1"
            headers = {
                "accept": "application/json",
                "Authorization": self.config["taostats_api_key"]
            }

            # Get events from the last 10 minutes (600 seconds)
            # This ensures we don't miss events even if the script is restarted
            current_time = int(time.time())
            from_time = current_time - 600

            params = {
                "from": from_time,
                "to": current_time,
                "amount_min": 0  # We'll filter by amount later
            }

            logger.debug(f"Fetching delegation events from {url}")
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                events = data.get("data", [])

                logger.info(f"Found {len(events)} delegation events in the last 10 minutes")

                # Process each event
                logger.info(f"Processing {len(events)} delegation events")
                for i, event in enumerate(events):
                    try:
                        # Get event type (delegation or undelegation)
                        action = event.get("action", "").lower()
                        event_type = "Delegation" if action == "delegate" else "Undelegation"

                        # Extract event data
                        event_id = f"{event.get('block_number')}_{event.get('nominator')}_{event.get('delegate')}"

                        # Log basic event info
                        logger.info(f"Event {i+1}/{len(events)}: {event_type} event_id={event_id}")

                        # Skip if we've already seen this event
                        if event_id in self.seen_events:
                            logger.info(f"  Skipping already seen event: {event_id}")
                            continue

                        # Mark as seen to avoid duplicates
                        self.seen_events[event_id] = time.time()

                        # Clean up old events from seen_events (older than 1 hour)
                        current_time = time.time()
                        self.seen_events = {k: v for k, v in self.seen_events.items() if current_time - v < 3600}

                        # Log the number of events we're tracking to monitor memory usage
                        if len(self.seen_events) > 1000:
                            logger.warning(f"Tracking a large number of events: {len(self.seen_events)}. Consider adjusting cleanup interval.")

                        # Extract event details
                        netuid = event.get("netuid")
                        logger.info(f"  Subnet: {netuid}")

                        # Skip subnet 0 if configured to do so
                        if netuid == 0 and self.config.get("exclude_subnet_0", True):
                            logger.info(f"  Skipping subnet 0 (excluded in config)")
                            continue

                        # Convert netuid to int if it's a string
                        if isinstance(netuid, str):
                            netuid = int(netuid)

                        # Get amount in nano TAO (rao)
                        amount_nano = float(event.get("amount", 0))
                        amount_tao = nano_to_tao(amount_nano)
                        logger.info(f"  Amount: {amount_tao:.2f} TAO")

                        # Skip events with 0 TAO
                        if amount_tao <= 0:
                            logger.info(f"  Skipping event with 0 TAO")
                            continue

                        # Extract nominator (coldkey)
                        nominator = event.get("nominator", {}).get("ss58", "Unknown")
                        logger.info(f"  Nominator: {nominator}")

                        # Determine if this is a low volume subnet
                        is_low_volume = False
                        subnet_volume_tao = 0
                        if netuid in self.subnet_volumes:
                            subnet_volume_tao = nano_to_tao(self.subnet_volumes[netuid])
                            is_low_volume = subnet_volume_tao < self.config["low_volume_threshold"]
                            logger.info(f"  Subnet {netuid} volume: {subnet_volume_tao:.2f} TAO ({'Low' if is_low_volume else 'High'} volume)")
                        else:
                            logger.info(f"  Subnet {netuid} volume data not available")

                        # Check if this event meets our threshold criteria (10+ TAO regardless of subnet volume)
                        should_alert = False
                        logger.info(f"  Checking threshold - minimum: {self.config['delegation_any_volume']} TAO for all subnets")

                        if amount_tao >= self.config["delegation_any_volume"]:
                            should_alert = True
                            logger.info(f"  Delegation event detected: {amount_tao:.2f} TAO on subnet {netuid}")
                        else:
                            logger.info(f"  Event does not meet threshold criteria (less than {self.config['delegation_any_volume']} TAO)")

                        # Check for related events (validator switch detection)
                        event_key = (nominator, netuid)
                        current_event_data = {
                            "action": action,
                            "amount": amount_tao,
                            "timestamp": time.time(),
                            "event_id": event_id,
                            "volume_percentage": (amount_nano / self.subnet_volumes[netuid]) * 100 if netuid in self.subnet_volumes and self.subnet_volumes[netuid] > 0 else 0,
                            "is_low_volume": is_low_volume,
                            "subnet_volume_tao": subnet_volume_tao,
                            "coldkey": nominator
                        }

                        # Check if we have a recent related event from the same coldkey on the same subnet
                        is_validator_switch = False
                        previous_event = None

                        if event_key in self.recent_delegation_events:
                            previous_event = self.recent_delegation_events[event_key]
                            time_diff = current_event_data["timestamp"] - previous_event["timestamp"]

                            # If the previous event was within 5 minutes and is a different action type
                            if time_diff < 300 and previous_event["action"] != action:
                                is_validator_switch = True
                                logger.info(f"  Detected validator switch: {previous_event['action']} → {action} within {time_diff:.1f} seconds")

                        # Update the recent events tracking
                        self.recent_delegation_events[event_key] = current_event_data

                        # Track subnet-level events for zero-sum detection
                        if netuid not in self.subnet_delegation_events:
                            self.subnet_delegation_events[netuid] = []

                        # Add current event to subnet events
                        self.subnet_delegation_events[netuid].append(current_event_data)

                        # Check for zero-sum events (delegation and undelegation of similar amounts)
                        is_zero_sum = False
                        zero_sum_pair = None

                        # Only check for zero-sum if we have at least 2 events for this subnet
                        if len(self.subnet_delegation_events[netuid]) >= 2:
                            # Get recent events for this subnet (last 5 minutes)
                            current_time = time.time()
                            recent_events = [e for e in self.subnet_delegation_events[netuid]
                                            if current_time - e["timestamp"] < 300]  # 5 minutes

                            # Group events by coldkey
                            coldkey_events = {}
                            for e in recent_events:
                                if e["coldkey"] not in coldkey_events:
                                    coldkey_events[e["coldkey"]] = []
                                coldkey_events[e["coldkey"]].append(e)

                            # Check each coldkey's events for zero-sum pairs
                            for coldkey, events in coldkey_events.items():
                                if len(events) >= 2:
                                    # Find delegation and undelegation pairs
                                    delegations = [e for e in events if e["action"] == "delegate"]
                                    undelegations = [e for e in events if e["action"] == "undelegate"]

                                    # Check each delegation against each undelegation
                                    for d in delegations:
                                        for u in undelegations:
                                            # Calculate the difference as a percentage
                                            amount_diff_pct = abs(d["amount"] - u["amount"]) / max(d["amount"], u["amount"]) * 100

                                            # If amounts are within 25% of each other, consider it a zero-sum
                                            if amount_diff_pct <= 25:
                                                is_zero_sum = True
                                                zero_sum_pair = (d, u)
                                                logger.info(f"  Detected zero-sum event: delegation of {d['amount']:.2f} TAO and undelegation of {u['amount']:.2f} TAO (diff: {amount_diff_pct:.1f}%)")
                                                break
                                        if is_zero_sum:
                                            break
                                if is_zero_sum:
                                    break

                        # Clean up old events (older than 10 minutes)
                        current_time = time.time()
                        for k in list(self.recent_delegation_events.keys()):
                            if current_time - self.recent_delegation_events[k]["timestamp"] > 600:  # 10 minutes
                                del self.recent_delegation_events[k]

                        # Clean up old subnet events
                        for netuid in list(self.subnet_delegation_events.keys()):
                            self.subnet_delegation_events[netuid] = [
                                e for e in self.subnet_delegation_events[netuid]
                                if current_time - e["timestamp"] < 600  # 10 minutes
                            ]

                        # Summary log
                        logger.info(f"  Summary: {event_type} of {amount_tao:.2f} TAO on subnet {netuid}, is_low_volume: {is_low_volume}, should_alert: {should_alert}, is_validator_switch: {is_validator_switch}, is_zero_sum: {is_zero_sum}")

                        # If this is a zero-sum event, skip notification entirely
                        if is_zero_sum:
                            logger.info(f"  Skipping notification for zero-sum event (delegation and undelegation of similar amounts)")
                            continue

                        # If this is part of a validator switch, only alert on the last action (delegation)
                        if is_validator_switch and action != "delegate":
                            logger.info(f"  Skipping notification for undelegation part of validator switch")
                            continue

                        # Determine the action type for fingerprinting
                        fingerprint_action = action
                        if is_validator_switch:
                            fingerprint_action = "validator_switch"

                        # Check if we've seen a similar event recently using our fingerprinting system
                        if not self.check_event_fingerprint(netuid, fingerprint_action, amount_tao, cooldown_seconds=300):
                            logger.info(f"  Skipping notification due to fingerprint cooldown")
                            continue

                        if should_alert:
                            # Get event type (delegation or undelegation)
                            action = event.get("action", "").lower()

                            # Get percentage of daily volume
                            volume_percentage = 0
                            if netuid in self.subnet_volumes and self.subnet_volumes[netuid] > 0:
                                volume_percentage = (amount_nano / self.subnet_volumes[netuid]) * 100

                            # Create notification message
                            if action == "delegate":
                                emoji = "🟢"
                                action_text = "DELEGATION"
                            else:  # undelegation
                                emoji = "🔴"
                                action_text = "UNDELEGATION"

                            # Get alpha token name
                            alpha_name = self.get_alpha_name_for_subnet(netuid)

                            # Determine if this is a validator switch
                            if is_validator_switch:
                                emoji = "🔄"
                                action_text = "VALIDATOR SWITCH"
                                message = f"{emoji} <b>{action_text}</b>\n\n"
                                message += f"Subnet: <b>{netuid}</b> ({alpha_name.upper()})\n"

                                # Include both amounts if we have the previous event
                                if previous_event:
                                    message += f"Amount: <b>{amount_tao:.2f} TAO</b>\n"
                                    message += f"Previous Amount: {previous_event['amount']:.2f} TAO\n"
                                else:
                                    message += f"Amount: <b>{amount_tao:.2f} TAO</b>\n"
                            else:
                                message = f"{emoji} <b>{action_text} EVENT</b>\n\n"
                                message += f"Subnet: <b>{netuid}</b> ({alpha_name.upper()})\n"
                                message += f"Amount: <b>{amount_tao:.2f} TAO</b>\n"

                            # Add volume context
                            if netuid in self.subnet_volumes:
                                subnet_volume_tao = nano_to_tao(self.subnet_volumes[netuid])
                                message += f"Subnet 24h Volume: {subnet_volume_tao:.2f} TAO\n"

                                if volume_percentage > 0:
                                    message += f"% of Daily Volume: <b>{volume_percentage:.2f}%</b>\n"

                            # Add trading tip based on action and volume
                            if is_validator_switch:
                                if is_low_volume and volume_percentage > 10:
                                    message += f"\n💡 <b>Trading Tip:</b> Validator switch on low volume subnet. This is typically neutral for price."
                                elif volume_percentage > 5:
                                    message += f"\n💡 <b>Trading Tip:</b> Significant validator switch relative to daily volume."
                            elif action == "delegate":
                                if is_low_volume and volume_percentage > 10:
                                    message += f"\n💡 <b>Trading Tip:</b> Large delegation on low volume subnet. Potential price impact!"
                                elif volume_percentage > 5:
                                    message += f"\n💡 <b>Trading Tip:</b> Significant delegation relative to daily volume."
                            else:  # undelegation
                                if is_low_volume and volume_percentage > 10:
                                    message += f"\n💡 <b>Trading Tip:</b> Large undelegation on low volume subnet. Watch for price impact!"

                            # Send the Telegram notification
                            self.send_telegram_message(message)
                            if is_validator_switch:
                                logger.info(f"Validator switch notification sent: {amount_tao:.2f} TAO on subnet {netuid}")
                            else:
                                logger.info(f"Delegation event notification sent: {action} of {amount_tao:.2f} TAO on subnet {netuid}")

                    except Exception as e:
                        logger.error(f"Error processing delegation event: {str(e)}")

                return True
            else:
                logger.warning(f"Failed to get delegation events: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error monitoring delegation events: {str(e)}")
            return False

    async def monitor_neuron_registrations(self):
        """Monitor neuron registrations, especially on low-volume subnets"""
        try:
            # Check API rate limit before making the call
            await self.check_api_rate_limit()

            # Get neuron registration events from TaoStats API
            url = "https://api.taostats.io/api/subnet/neuron/registration/v1"
            headers = {
                "accept": "application/json",
                "Authorization": self.config["taostats_api_key"]
            }

            # Get registrations from the last 10 minutes (600 seconds)
            current_time = int(time.time())
            from_time = current_time - 600

            params = {
                "from": from_time,
                "to": current_time
            }

            logger.debug(f"Fetching neuron registrations from {url}")
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                registrations = data.get("data", [])

                logger.info(f"Found {len(registrations)} neuron registrations in the last 10 minutes")

                # Log the first registration for debugging if available
                if registrations and len(registrations) > 0:
                    logger.debug(f"First registration structure: {json.dumps(registrations[0], indent=2)}")

                # Process each registration
                for reg in registrations:
                    try:
                        # Extract registration data
                        reg_id = f"{reg.get('block_number')}_{reg.get('hotkey')}"

                        # Skip if we've already seen this registration
                        if reg_id in self.seen_events:
                            continue

                        # Mark as seen to avoid duplicates
                        self.seen_events[reg_id] = time.time()

                        # Extract registration details
                        netuid = reg.get("netuid")
                        block_number = reg.get("block_number")
                        timestamp_str = reg.get("timestamp")

                        # Convert timestamp to int if it's a string
                        if isinstance(timestamp_str, str):
                            # Parse timestamp string to get a timestamp integer
                            try:
                                # Try parsing ISO format timestamp
                                from datetime import datetime
                                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                timestamp = int(dt.timestamp())
                            except:
                                # If parsing fails, use current time
                                timestamp = int(time.time())
                        else:
                            timestamp = int(time.time())

                        # Skip subnet 0 if configured to do so
                        if netuid == 0 and self.config.get("exclude_subnet_0", True):
                            continue

                        # Convert netuid to int if it's a string
                        if isinstance(netuid, str):
                            netuid = int(netuid)

                        # Add to registration tracking
                        self.registrations[netuid].append(timestamp)

                        # Determine if this is a low volume subnet
                        is_low_volume = False
                        if netuid in self.subnet_volumes:
                            subnet_volume_tao = nano_to_tao(self.subnet_volumes[netuid])
                            is_low_volume = subnet_volume_tao < self.config["low_volume_threshold"]

                        # Only alert for registrations on low volume subnets
                        if is_low_volume:
                            # Check for registration burst (multiple registrations in a short time)
                            # Get registrations in the burst window
                            burst_window = self.config["burst_window"]  # seconds
                            current_time = int(time.time())
                            recent_registrations = [t for t in self.registrations[netuid]
                                                  if current_time - t < burst_window]

                            # If we have enough registrations in the burst window, alert
                            if len(recent_registrations) >= self.config["registration_burst"]:
                                # Get alpha token name
                                alpha_name = self.get_alpha_name_for_subnet(netuid)

                                # Create notification message
                                message = f"🔔 <b>REGISTRATION BURST DETECTED!</b>\n\n"
                                message += f"Subnet: <b>{netuid}</b> ({alpha_name.upper()})\n"
                                message += f"Registrations: <b>{len(recent_registrations)}</b> in the last {burst_window//60} minutes\n"

                                # Add volume context
                                if netuid in self.subnet_volumes:
                                    subnet_volume_tao = nano_to_tao(self.subnet_volumes[netuid])
                                    message += f"Subnet 24h Volume: {subnet_volume_tao:.2f} TAO\n"

                                # Add trading tip
                                message += f"\n💡 <b>Trading Tip:</b> Multiple registrations on a low volume subnet could indicate upcoming activity."

                                # Check if we've seen a similar registration burst recently using our fingerprinting system
                                if self.check_event_fingerprint(netuid, "registration_burst", len(recent_registrations), cooldown_seconds=1800):  # 30 minute cooldown
                                    # Send the Telegram notification
                                    self.send_telegram_message(message)
                                    logger.info(f"Registration burst notification sent: {len(recent_registrations)} registrations on subnet {netuid}")
                                else:
                                    logger.info(f"Skipping registration burst notification due to fingerprint cooldown")

                                # Clear the registrations for this subnet to avoid repeated alerts
                                self.registrations[netuid].clear()

                    except Exception as e:
                        logger.error(f"Error processing neuron registration: {str(e)}")

                return True
            else:
                logger.warning(f"Failed to get neuron registrations: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error monitoring neuron registrations: {str(e)}")
            return False

    def extract_ss58_address(self, owner_data):
        """Extract SS58 address from owner data which could be a string or a dict"""
        if isinstance(owner_data, str):
            return owner_data
        elif isinstance(owner_data, dict) and 'ss58' in owner_data:
            return owner_data['ss58']
        else:
            # Try to convert to string and extract
            try:
                owner_str = str(owner_data)
                # Check if it's a JSON string
                if owner_str.startswith('{') and owner_str.endswith('}'):
                    import json
                    try:
                        owner_dict = json.loads(owner_str.replace("'", '"'))
                        if 'ss58' in owner_dict:
                            return owner_dict['ss58']
                    except:
                        pass
                return owner_str
            except:
                return str(owner_data)

    async def monitor_scheduled_coldkey_swaps(self, subtensor):
        """Monitor for scheduled coldkey swaps that indicate upcoming subnet ownership changes"""
        try:
            # Check API rate limit before making the call
            await self.check_api_rate_limit()

            # Get the current block
            current_block = await subtensor.get_current_block()

            # Skip if we've already checked this block
            if current_block <= self.last_checked_block:
                return

            logger.info(f"Checking for scheduled coldkey swaps in blocks {self.last_checked_block+1} to {current_block}")

            # Get all extrinsics from TaoStats API for the block range
            url = "https://api.taostats.io/api/extrinsic/v1"
            headers = {
                "accept": "application/json",
                "Authorization": self.config["taostats_api_key"]
            }

            # Set parameters for the API call - get all extrinsics from the subtensorModule
            params = {
                "block_min": self.last_checked_block + 1,
                "block_max": current_block,
                "module": "subtensorModule",
                "limit": 100,  # Get a larger number of extrinsics
                "full_name": "SubtensorModule.scheduleSwapColdkey"  # Specifically filter for coldkey swap extrinsics
            }

            logger.info(f"Fetching extrinsics from {url} with params {params}")
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                all_extrinsics = data.get("data", [])

                logger.info(f"Found {len(all_extrinsics)} subtensorModule extrinsics")

                # Filter for scheduleSwapColdkey extrinsics
                coldkey_swap_extrinsics = []
                for extrinsic in all_extrinsics:
                    full_name = extrinsic.get("full_name", "")
                    call_name = extrinsic.get("call_name", "")

                    # Check both full_name and call_name fields for flexibility
                    if "scheduleSwapColdkey" in full_name or "scheduleSwapColdkey" in call_name:
                        coldkey_swap_extrinsics.append(extrinsic)

                logger.info(f"Found {len(coldkey_swap_extrinsics)} scheduleSwapColdkey extrinsics")

                # If we found any coldkey swap extrinsics, log the first one for debugging
                if coldkey_swap_extrinsics and len(coldkey_swap_extrinsics) > 0:
                    logger.debug(f"First coldkey swap extrinsic structure: {json.dumps(coldkey_swap_extrinsics[0], indent=2)}")

                # Only refresh subnet owners if needed
                current_time = time.time()
                if not self.subnet_owners or (current_time - self.last_subnet_owners_refresh) > self.subnet_owners_refresh_interval:
                    logger.info("Refreshing subnet owners cache")
                    self.subnet_owners = await self.get_all_subnet_owners()
                    self.last_subnet_owners_refresh = current_time
                    logger.info(f"Refreshed {len(self.subnet_owners)} subnet owners")
                else:
                    logger.debug(f"Using cached subnet owners ({len(self.subnet_owners)} subnets)")

                # Process each scheduled coldkey swap
                for extrinsic in coldkey_swap_extrinsics:
                    try:
                        # Extract extrinsic details
                        block_number = extrinsic.get("block_number")
                        source_coldkey = extrinsic.get("signer_address")

                        # Convert hex to SS58 if needed
                        if source_coldkey and source_coldkey.startswith("0x"):
                            try:
                                source_coldkey = self.hex_to_ss58(source_coldkey)
                            except Exception as e:
                                logger.error(f"Error converting hex to SS58: {str(e)}")

                        # Get the destination coldkey from call_args
                        call_args = extrinsic.get("call_args", {})
                        destination_coldkey = call_args.get("newColdkey")

                        logger.info(f"Processing coldkey swap: block={block_number}, source={source_coldkey}, destination={destination_coldkey}")

                        # Skip if missing data
                        if not source_coldkey or not destination_coldkey:
                            logger.info(f"Skipping coldkey swap due to missing data")
                            continue

                        # Create a unique event ID for deduplication
                        event_id = f"scheduled_coldkey_swap_{block_number}_{source_coldkey}_{destination_coldkey}"

                        # Skip if we've already seen this event
                        if event_id in self.seen_events:
                            logger.info(f"Skipping already seen coldkey swap event: {event_id}")
                            continue

                        # Mark as seen to avoid duplicates
                        self.seen_events[event_id] = time.time()

                        # Clean up old events from seen_events (older than 1 day)
                        current_time = time.time()
                        self.seen_events = {k: v for k, v in self.seen_events.items() if current_time - v < 86400}

                        # Check if the source coldkey is a subnet owner
                        owned_subnets = []
                        for netuid, owner in self.subnet_owners.items():
                            # Skip subnet 0 if configured to do so
                            if netuid == 0 and self.config.get("exclude_subnet_0", True):
                                continue

                            owner_ss58 = self.extract_ss58_address(owner)
                            logger.debug(f"Checking subnet {netuid} owner: {owner_ss58}")
                            if owner_ss58 == source_coldkey:
                                owned_subnets.append(netuid)
                                logger.info(f"Found match! Subnet {netuid} is owned by {source_coldkey}")

                        # If the source coldkey doesn't own any subnets, skip
                        if not owned_subnets:
                            logger.info(f"Coldkey {source_coldkey} doesn't own any subnets, skipping")
                            continue

                        # Format owner addresses safely
                        source_display = source_coldkey
                        if len(source_coldkey) > 20:
                            source_display = f"{source_coldkey[:10]}...{source_coldkey[-6:]}"

                        destination_display = destination_coldkey
                        if len(destination_coldkey) > 20:
                            destination_display = f"{destination_coldkey[:10]}...{destination_coldkey[-6:]}"

                        # Create notification message
                        message = f"🔄 <b>SCHEDULED SUBNET OWNERSHIP TRANSFER DETECTED!</b>\n\n"
                        message += f"Source Coldkey: <code>{source_display}</code>\n"
                        message += f"Destination Coldkey: <code>{destination_display}</code>\n"
                        message += f"Block: <code>{block_number}</code>\n\n"
                        message += f"<b>Affected Subnets:</b>\n"

                        # Add information about each affected subnet
                        for netuid in owned_subnets:
                            # Get alpha token name
                            alpha_name = self.get_alpha_name_for_subnet(netuid)

                            message += f"• Subnet <b>{netuid}</b> ({alpha_name.upper()})"

                            # Add volume context
                            if netuid in self.subnet_volumes:
                                subnet_volume_tao = nano_to_tao(self.subnet_volumes[netuid])
                                message += f" - 24h Volume: {subnet_volume_tao:.2f} TAO"

                            message += "\n"

                        # Add trading tip
                        message += f"\n💡 <b>Trading Tip:</b> This scheduled coldkey swap will transfer subnet ownership in 5 days. This may indicate significant changes in subnet direction or tokenomics."

                        # Log the coldkey swap to a separate file for external scripts to use
                        try:
                            coldkey_swap_data = {
                                "block_number": block_number,
                                "source_coldkey": source_coldkey,
                                "destination_coldkey": destination_coldkey,
                                "owned_subnets": owned_subnets,
                                "timestamp": datetime.now().isoformat()
                            }

                            # Write to the coldkey swaps log file
                            with open("coldkey_swaps.log", "a") as f:
                                f.write(json.dumps(coldkey_swap_data) + "\n")
                            logger.info(f"Logged coldkey swap to coldkey_swaps.log: {owned_subnets}")
                        except Exception as e:
                            logger.error(f"Error logging coldkey swap to file: {str(e)}")

                        # Check if we've seen a similar coldkey swap recently using our fingerprinting system
                        # Use the first subnet as the key for fingerprinting
                        if owned_subnets and self.check_event_fingerprint(owned_subnets[0], "coldkey_swap", len(owned_subnets), cooldown_seconds=3600):  # 1 hour cooldown
                            # Send the Telegram notification
                            self.send_telegram_message(message)
                            logger.info(f"Scheduled coldkey swap notification sent for {len(owned_subnets)} subnets")
                        else:
                            logger.info(f"Skipping coldkey swap notification due to fingerprint cooldown")

                    except Exception as e:
                        logger.error(f"Error processing scheduled coldkey swap: {str(e)}")

                # Update last checked block
                self.last_checked_block = current_block

                return True
            else:
                logger.warning(f"Failed to get extrinsics: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error monitoring scheduled coldkey swaps: {str(e)}")
            return False

    def hex_to_ss58(self, hex_address):
        """Convert a hex address to SS58 format"""
        try:
            from substrateinterface import Keypair

            # Remove '0x' prefix if present
            if hex_address.startswith('0x'):
                hex_address = hex_address[2:]

            # Create a keypair from the public key
            keypair = Keypair(public_key=bytes.fromhex(hex_address), ss58_format=42)

            # Return the SS58 address
            return keypair.ss58_address
        except Exception as e:
            logger.error(f"Error converting hex to SS58: {str(e)}")
            return hex_address

    async def get_all_subnet_owners(self):
        """Get all subnet owners from TaoStats API with pagination support"""
        try:
            # Create a dictionary of subnet owners
            subnet_owners = {}
            current_page = 1
            total_pages = 1  # Will be updated after first request

            # Fetch all pages
            while current_page <= total_pages:
                # Check API rate limit before making the call
                await self.check_api_rate_limit()

                url = "https://api.taostats.io/api/subnet/owner/v1"
                headers = {
                    "accept": "application/json",
                    "Authorization": self.config["taostats_api_key"]
                }

                # Add page parameter
                params = {
                    "page": current_page
                }

                logger.debug(f"Fetching subnet owners from {url} (page {current_page}/{total_pages})")
                response = requests.get(url, headers=headers, params=params, timeout=30)

                if response.status_code == 200:
                    data = response.json()

                    # Update total pages from pagination info
                    pagination = data.get("pagination", {})
                    total_pages = pagination.get("total_pages", 1)

                    subnet_owners_data = data.get("data", [])
                    logger.debug(f"Received {len(subnet_owners_data)} subnet owners on page {current_page}")

                    # Process each subnet
                    for subnet_data in subnet_owners_data:
                        try:
                            netuid = subnet_data.get("netuid")
                            owner = subnet_data.get("owner")

                            # Skip if missing data
                            if netuid is None or owner is None:
                                continue

                            # Convert netuid to int if it's a string
                            if isinstance(netuid, str):
                                netuid = int(netuid)

                            # Store owner
                            subnet_owners[netuid] = owner

                        except Exception as e:
                            logger.error(f"Error processing subnet owner data: {str(e)}")

                    # Move to next page
                    current_page += 1
                else:
                    logger.warning(f"Failed to get subnet owners (page {current_page}): {response.status_code} - {response.text}")
                    break  # Stop on error

            logger.info(f"Retrieved {len(subnet_owners)} subnet owners from {total_pages} pages")
            return subnet_owners

        except Exception as e:
            logger.error(f"Error getting subnet owners: {str(e)}")
            return {}

    # Main execution methods

    async def run(self):
        """Main execution loop"""
        logger.info("Starting Bittensor Chain Monitor")
        self.running = True

        try:
            # Initialize subtensor connection
            async with bt.async_subtensor(network=self.config["network"]) as subtensor:
                # Get current block
                self.current_block = await subtensor.get_current_block()
                logger.info(f"Starting monitoring from block {self.current_block}")

                # Set last checked block
                self.last_checked_block = self.current_block - 1

                # Send initial Telegram message
                start_message = "🚀 <b>Bittensor Chain Monitor Started</b>\n\n"
                start_message += f"Network: <code>{self.config['network']}</code>\n"
                start_message += f"Current Block: <code>{self.current_block}</code>\n"
                start_message += f"Time: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
                start_message += "<b>Monitoring for:</b>\n"
                start_message += "• Delegations/Undelegations\n"
                start_message += "• Volume Spikes\n"
                start_message += "• Neuron Registrations\n"
                start_message += "• Scheduled Subnet Ownership Transfers"

                self.send_telegram_message(start_message)

                # Initial data fetches
                logger.info("Performing initial data fetches...")

                # Fetch subnet volumes
                await self.fetch_subnet_volumes()

                # Fetch subnet owners (only once at startup)
                logger.info("Fetching initial subnet owners data...")
                self.subnet_owners = await self.get_all_subnet_owners()
                self.last_subnet_owners_refresh = time.time()
                logger.info(f"Fetched {len(self.subnet_owners)} subnet owners")

                # Main monitoring loop
                while self.running:
                    try:
                        # Update volume data periodically
                        await self.fetch_subnet_volumes()

                        # Detect volume spikes
                        await self.detect_volume_spikes()

                        # Monitor delegation events
                        await self.monitor_delegation_events()

                        # Monitor neuron registrations
                        await self.monitor_neuron_registrations()

                        # Monitor scheduled coldkey swaps (which indicate upcoming subnet ownership changes)
                        await self.monitor_scheduled_coldkey_swaps(subtensor)

                        # Sleep to avoid excessive CPU usage
                        await asyncio.sleep(self.config["check_interval"])

                    except Exception as e:
                        logger.error(f"Error in monitoring loop: {str(e)}")
                        await asyncio.sleep(10)  # Sleep longer on error

        except Exception as e:
            logger.error(f"Fatal error in monitor: {str(e)}")
            self.running = False

            # Send error notification
            error_message = f"❌ <b>MONITOR ERROR</b>\n\n"
            error_message += f"The Bittensor monitor encountered a fatal error and stopped:\n"
            error_message += f"<code>{str(e)}</code>\n\n"
            error_message += f"Time: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
            self.send_telegram_message(error_message)

    def stop(self):
        """Stop the monitor"""
        self.running = False
        logger.info("Stopping Bittensor Chain Monitor")

        # Send stop notification
        stop_message = f"🛑 <b>MONITOR STOPPED</b>\n\n"
        stop_message += f"The Bittensor monitor was manually stopped.\n"
        stop_message += f"Time: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
        self.send_telegram_message(stop_message)

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Bittensor Chain Monitor - A focused monitoring suite")
    parser.add_argument("--config", type=str, help="Path to configuration file")
    parser.add_argument("--network", default=None, help="Bittensor network to connect to")
    parser.add_argument("--telegram-token", help="Telegram bot token")
    parser.add_argument("--telegram-chat-id", help="Telegram chat ID")
    parser.add_argument("--taostats-api-key", help="TaoStats API key")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Load configuration
    config = DEFAULT_CONFIG.copy()

    # Load config from file if provided
    if args.config:
        try:
            with open(args.config, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            logger.error(f"Error loading configuration file: {str(e)}")

    # Override config with command-line arguments
    if args.network:
        config["network"] = args.network

    if args.telegram_token:
        config["telegram_token"] = args.telegram_token

    if args.telegram_chat_id:
        config["telegram_chat_id"] = args.telegram_chat_id

    if args.taostats_api_key:
        config["taostats_api_key"] = args.taostats_api_key

    if args.debug:
        config["debug"] = True

    # Create and run the monitor
    monitor = BittensorChainMonitor(config)

    try:
        await monitor.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
        monitor.stop()
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        monitor.stop()

if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())
