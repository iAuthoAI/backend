import boto3
from botocore.exceptions import ClientError

def load_parameter_store(prefix: str = "/oneclick", region: str = "us-east-2") -> dict:
    """Fetch all parameters from AWS Parameter Store."""
    try:
        client = boto3.client("ssm", region_name=region)
        params = {}
        paginator = client.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=prefix, Recursive=True, WithDecryption=True):
            for p in page["Parameters"]:
                params[p["Name"]] = p["Value"]
        return params
    except Exception:
        return {}
