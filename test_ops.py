import os
import httpx
import json

AUTOTASK_API_URL = os.environ.get("AUTOTASK_API_URL")
AUTOTASK_USERNAME = os.environ.get("AUTOTASK_USERNAME")
AUTOTASK_SECRET = os.environ.get("AUTOTASK_SECRET")
AUTOTASK_INTEGRATION_CODE = os.environ.get("AUTOTASK_INTEGRATION_CODE")

headers = {
    "Content-Type": "application/json",
    "UserName": AUTOTASK_USERNAME,
    "Secret": AUTOTASK_SECRET,
    "ApiIntegrationcode": AUTOTASK_INTEGRATION_CODE,
}

def test_operator(op, value):
    print(f"\nTesting operator: {op}")
    query = {
        "MaxRecords": 1,
        "filter": [{"op": op, "field": "status", "value": value}]
    }
    url = f"{AUTOTASK_API_URL}/Tickets/query"
    try:
        response = httpx.post(url, headers=headers, json=query, timeout=10.0)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            items = response.json().get("items", [])
            if items:
                print(f"Found ticket with status: {items[0].get('status')}")
                if items[0].get('status') == value:
                    print(f"FAILED: Found status {value} when we tried to exclude it!")
                else:
                    print(f"SUCCESS: Operator {op} excluded {value}")
            else:
                print("No tickets found.")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    # Test common 'not equal' operators
    for op in ["notequal", "noteq", "neq", "notEqual", "ne"]:
        test_operator(op, 5)
