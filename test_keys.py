"""Quick test to verify all API keys work."""
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


print("Testing API keys...\n")

# Test Gemini via CrewAI's LLM
try:
    from crewai import LLM
    llm = LLM(model="gemini/gemini-2.0-flash")
    response = llm.call(messages=[{"role": "user", "content": "Say hello in one word."}])
    print(f"  Gemini:  OK - {str(response).strip()[:60]}")
except Exception as e:
    print(f"  Gemini:  FAILED - {e}")

# Test Apollo
try:
    r = requests.post(
        "https://api.apollo.io/v1/mixed_people/search",
        headers={"Content-Type": "application/json",
                 "X-Api-Key": os.getenv("APOLLO_API_KEY")},
        json={"q_keywords": "test", "per_page": 1},
        timeout=15,
    )
    if r.status_code == 200:
        print(f"  Apollo:  OK")
    else:
        print(f"  Apollo:  HTTP {r.status_code} - {r.text[:80]}")
except Exception as e:
    print(f"  Apollo:  FAILED - {e}")

# Test Hunter
try:
    r2 = requests.get(
        "https://api.hunter.io/v2/account",
        params={"api_key": os.getenv("HUNTER_API_KEY")},
        timeout=15,
    )
    if r2.status_code == 200:
        data = r2.json().get("data", {})
        print(f"  Hunter:  OK - {data.get('email', 'connected')}")
    else:
        print(f"  Hunter:  HTTP {r2.status_code} - {r2.text[:80]}")
except Exception as e:
    print(f"  Hunter:  FAILED - {e}")

print("\nDone!")
