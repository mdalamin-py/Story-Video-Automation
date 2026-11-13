"""Optional private S3 archive for completed previews."""
import hashlib
import os


def archive_preview(path, run):
    bucket = os.environ.get("STUDIO_S3_BUCKET", "").strip()
    if not bucket:
        return None
    import boto3

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    checksum = digest.hexdigest()
    key = f"previews/{run}/{checksum}.mp4"
    client = boto3.client("s3", endpoint_url=os.environ.get("STUDIO_S3_ENDPOINT") or None)
    client.upload_file(str(path), bucket, key, ExtraArgs={
        "ContentType": "video/mp4", "Metadata": {"sha256": checksum},
    })
    return {"bucket": bucket, "key": key, "sha256": checksum, "size": path.stat().st_size}
