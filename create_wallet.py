import bittensor as bt

# Create a new wallet with coldkey "miners" and hotkey "miner_1"
wallet = bt.wallet(name="miners", hotkey="miner_1")
wallet.create_if_non_existent(coldkey_use_password=True, hotkey_use_password=True)

print(f"Wallet created: {wallet}")
print(f"Coldkey address: {wallet.coldkeypub.ss58_address}")
print(f"Hotkey address: {wallet.hotkey.ss58_address}")
