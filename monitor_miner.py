#!/usr/bin/env python3

# Add the current directory to the Python path
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import asyncio
import time
import json
import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import bittensor as bt

class MinerMonitor:
    def __init__(self, netuid, wallet_name, hotkey_name):
        self.netuid = netuid
        self.wallet_name = wallet_name
        self.hotkey_name = hotkey_name
        self.wallet = bt.wallet(name=wallet_name, hotkey=hotkey_name)
        self.subtensor = bt.subtensor()
        self.metagraph = self.subtensor.metagraph(netuid)
        self.history_file = f"miner_history_{wallet_name}_{hotkey_name}.json"
        self.history = self.load_history()

    def load_history(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as f:
                return json.load(f)
        return {"timestamps": [], "stakes": [], "ranks": [], "trust": [], "consensus": [], "incentive": [], "dividends": []}

    def save_history(self):
        with open(self.history_file, 'w') as f:
            json.dump(self.history, f)

    def get_uid_for_hotkey(self):
        for uid, hotkey in enumerate(self.metagraph.hotkeys):
            if self.wallet.hotkey.ss58_address == hotkey:
                return uid
        return None

    def update_metagraph(self):
        self.metagraph = self.subtensor.metagraph(self.netuid)

    def get_miner_stats(self):
        uid = self.get_uid_for_hotkey()
        if uid is None:
            print(f"Hotkey {self.wallet.hotkey.ss58_address} not found in metagraph")
            return None

        return {
            "uid": uid,
            "stake": self.metagraph.S[uid].item(),
            "rank": self.metagraph.R[uid].item(),
            "trust": self.metagraph.T[uid].item(),
            "consensus": self.metagraph.C[uid].item(),
            "incentive": self.metagraph.I[uid].item(),
            "dividends": self.metagraph.D[uid].item(),
            "emission": self.subtensor.get_emission_value_by_uid(self.netuid, uid)
        }

    def update_history(self, stats):
        if stats is None:
            return

        self.history["timestamps"].append(time.time())
        self.history["stakes"].append(stats["stake"])
        self.history["ranks"].append(stats["rank"])
        self.history["trust"].append(stats["trust"])
        self.history["consensus"].append(stats["consensus"])
        self.history["incentive"].append(stats["incentive"])
        self.history["dividends"].append(stats["dividends"])

        # Keep only last 30 days of data
        max_entries = 30 * 24 * 6  # 30 days with 10-minute intervals
        if len(self.history["timestamps"]) > max_entries:
            for key in self.history:
                self.history[key] = self.history[key][-max_entries:]

        self.save_history()

    def plot_history(self):
        if not self.history["timestamps"]:
            print("No history data available")
            return

        # Convert timestamps to datetime
        dates = [datetime.fromtimestamp(ts) for ts in self.history["timestamps"]]

        # Create DataFrame
        df = pd.DataFrame({
            'Date': dates,
            'Rank': self.history["ranks"],
            'Trust': self.history["trust"],
            'Consensus': self.history["consensus"],
            'Incentive': self.history["incentive"],
            'Dividends': self.history["dividends"],
            'Stake': self.history["stakes"]
        })

        # Plot metrics
        fig, axes = plt.subplots(3, 1, figsize=(12, 18))

        # Plot rank and incentive
        ax1 = axes[0]
        ax1.plot(df['Date'], df['Rank'], 'b-', label='Rank')
        ax1.plot(df['Date'], df['Incentive'], 'r-', label='Incentive')
        ax1.set_title('Rank and Incentive Over Time')
        ax1.set_ylabel('Value')
        ax1.legend()
        ax1.grid(True)

        # Plot trust and consensus
        ax2 = axes[1]
        ax2.plot(df['Date'], df['Trust'], 'g-', label='Trust')
        ax2.plot(df['Date'], df['Consensus'], 'y-', label='Consensus')
        ax2.set_title('Trust and Consensus Over Time')
        ax2.set_ylabel('Value')
        ax2.legend()
        ax2.grid(True)

        # Plot stake and dividends
        ax3 = axes[2]
        ax3.plot(df['Date'], df['Stake'], 'm-', label='Stake')
        ax3.plot(df['Date'], df['Dividends'], 'c-', label='Dividends')
        ax3.set_title('Stake and Dividends Over Time')
        ax3.set_ylabel('Value')
        ax3.legend()
        ax3.grid(True)

        plt.tight_layout()
        plt.savefig(f"miner_stats_{self.wallet_name}_{self.hotkey_name}.png")
        print(f"Plot saved to miner_stats_{self.wallet_name}_{self.hotkey_name}.png")

    def print_stats(self, stats):
        if stats is None:
            return

        print("\n" + "="*50)
        print(f"Miner Stats for {self.wallet_name}/{self.hotkey_name}")
        print("="*50)
        print(f"UID: {stats['uid']}")
        print(f"Stake: {stats['stake']:.4f} τ")
        print(f"Rank: {stats['rank']:.4f}")
        print(f"Trust: {stats['trust']:.4f}")
        print(f"Consensus: {stats['consensus']:.4f}")
        print(f"Incentive: {stats['incentive']:.4f}")
        print(f"Dividends: {stats['dividends']:.4f}")
        print(f"Emission: {stats['emission']:.8f} τ/day")

        # Calculate daily earnings
        daily_tao = stats['emission'] * 24
        print(f"Estimated Daily Earnings: {daily_tao:.8f} τ")
        print("="*50)

    def get_network_stats(self):
        total_stake = sum(self.metagraph.S)
        active_validators = sum(1 for v in self.metagraph.validator_permit if v)
        active_miners = sum(1 for s in self.metagraph.S if s > 0) - active_validators

        print("\n" + "="*50)
        print(f"Network Stats for Subnet {self.netuid}")
        print("="*50)
        print(f"Total Stake: {total_stake:.4f} τ")
        print(f"Active Validators: {active_validators}")
        print(f"Active Miners: {active_miners}")
        print("="*50)

    def get_miner_rank(self, stats):
        if stats is None:
            return None

        # Sort all miners by incentive
        incentives = [(i, self.metagraph.I[i].item()) for i in range(len(self.metagraph.I))]
        incentives.sort(key=lambda x: x[1], reverse=True)

        # Find our position
        for rank, (uid, _) in enumerate(incentives):
            if uid == stats['uid']:
                return rank + 1

        return None

    def print_miner_rank(self, rank):
        if rank is None:
            return

        total_miners = sum(1 for s in self.metagraph.S if s > 0)
        percentile = (total_miners - rank) / total_miners * 100

        print("\n" + "="*50)
        print(f"Miner Ranking")
        print("="*50)
        print(f"Your Rank: {rank} out of {total_miners} miners")
        print(f"Percentile: {percentile:.2f}%")
        print("="*50)

    async def run(self, interval=600, plot_interval=3600):
        last_plot_time = 0

        while True:
            try:
                self.update_metagraph()
                stats = self.get_miner_stats()
                self.update_history(stats)
                self.print_stats(stats)

                rank = self.get_miner_rank(stats)
                self.print_miner_rank(rank)

                self.get_network_stats()

                # Plot every hour
                current_time = time.time()
                if current_time - last_plot_time > plot_interval:
                    self.plot_history()
                    last_plot_time = current_time

                await asyncio.sleep(interval)
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(10)

def main():
    parser = argparse.ArgumentParser(description="Monitor Patrol subnet miner performance")
    parser.add_argument("--netuid", type=int, default=81, help="Subnet UID (default: 81)")
    parser.add_argument("--wallet.name", type=str, default="miners", help="Wallet name")
    parser.add_argument("--wallet.hotkey", type=str, default="miner_1", help="Hotkey name")
    parser.add_argument("--interval", type=int, default=600, help="Update interval in seconds (default: 600)")

    args = parser.parse_args()

    monitor = MinerMonitor(args.netuid, getattr(args.wallet, 'name'), getattr(args.wallet, 'hotkey'))

    try:
        asyncio.run(monitor.run(interval=args.interval))
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
