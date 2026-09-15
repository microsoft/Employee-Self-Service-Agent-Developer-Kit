import sys, json
sys.path.insert(0, "scripts")
from auth import authenticate
import requests

env_url = "https://org4cd8d7db.crm10.dynamics.com"
token = authenticate(env_url)
r = requests.get(
    f"{env_url}/api/data/v9.2/solutions",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    params={
        "$select": "uniquename,version,ismanaged",
        "$filter": "startswith(uniquename,'msdyn_copilotforemployeeselfservice') or startswith(uniquename,'msdyn_essh') or startswith(uniquename,'msdyn_essit')"
    }
)
r.raise_for_status()
print(json.dumps(r.json().get("value", []), indent=2))
