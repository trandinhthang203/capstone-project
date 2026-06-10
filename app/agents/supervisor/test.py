
import json

response = """
{
  "procedures": [],
  "fields": [],
  "pipeline": ["qa"]
}
"""

data = json.loads(response)


procedures = data.get("procedures", [])
print(procedures)