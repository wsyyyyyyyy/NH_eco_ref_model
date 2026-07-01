import os
from dotenv import set_key

env_file = ".env"
key = "GEMINI_API_KEY"
value = "AIzaSyBWxU-JjEcglcSX8Zz9VfFBkDNxCUeZOHY"

# Create .env file if it doesn't exist
if not os.path.exists(env_file):
    with open(env_file, "w") as f:
        pass

set_key(env_file, key, value)
print(f"Successfully saved {key} to {env_file}")
