import json
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "meta.llama3-70b-instruct-v1:0")

client = boto3.client("bedrock-runtime", region_name=REGION)

resp = client.invoke_model(
    modelId=MODEL_ID,
    body=json.dumps({"prompt": "Say hello in one word.", "max_gen_len": 32}),
)
print(resp["body"].read().decode())
