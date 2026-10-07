"""Write bytes to a local path or an s3:// URI. The only module that knows the difference"""
from pathlib import Path 

def write_bytes(uri: str, data: bytes) -> None: 
    if uri.startswith("s3://"):
        # Imported here, not at the top: local runs never touch S3, so they skip boto3's import cost. 
        import boto3

        # "s3://bucket/raw/fred/x.json" -> bucket="bucket", key="raw/fred/x.json"
        bucket, _, key = uri.removeprefix("s3://").partition("/")

        # Credentials come from the Fargate task role automatically; nothing to configure here. 
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=data)
    else: 
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    