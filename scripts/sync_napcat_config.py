"""Copy the deployment WebSocket client into NapCat's per-account config."""

import json
from pathlib import Path


config_dir = Path(__file__).resolve().parents[1] / "data" / "napcat" / "config"
source = json.loads((config_dir / "onebot11.json").read_text(encoding="utf-8"))
client = source["network"]["websocketClients"][0]

for path in config_dir.glob("onebot11_*.json"):
    account = json.loads(path.read_text(encoding="utf-8"))
    clients = account["network"].setdefault("websocketClients", [])
    clients[:] = [existing for existing in clients if existing.get("name") != client["name"]]
    clients.append(client)
    path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Synced reverse WebSocket client to {path.name}")
