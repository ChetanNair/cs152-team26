import json
import os
import requests

# There should be a file called 'tokens.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    tokens = json.load(f)
    perspective_token = tokens['perspective']

def get_perspective_scores(text):
    url = "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze"
    headers = {
        "Content-Type": "application/json",
    }
    data = {
        "comment": {
            "text": text
        },
        "languages": ["en"],
        "requestedAttributes": {
            "TOXICITY": {},
            "SEVERE_TOXICITY": {},
            "IDENTITY_ATTACK": {},
            "INSULT": {},
            "PROFANITY": {},
            "THREAT": {},
            "SEXUALLY_EXPLICIT": {},
            "FLIRTATION": {}
        }
    }
    
    response = requests.post(url, headers=headers, json=data, params={"key": perspective_token})
    if response.status_code == 200:
        response_json = response.json()
        scores = {attribute: response_json['attributeScores'][attribute]['summaryScore']['value'] 
                  for attribute in response_json['attributeScores']}
        return scores
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return None

