"""Optional private S3 archive for completed previews."""
import hashlib
import os


def s3_client():
    import boto3

    return boto3.client("s3", endpoint_url=os.environ.get("STUDIO_S3_ENDPOINT") or None)


def archive_preview(path, run):
    bucket = os.environ.get("STUDIO_S3_BUCKET", "").strip()
    if not bucket:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    checksum = digest.hexdigest()
    key = f"previews/{run}/{checksum}.mp4"
    client = s3_client()
    client.upload_file(str(path), bucket, key, ExtraArgs={
        "ContentType": "video/mp4", "Metadata": {"sha256": checksum},
    })
    return {"bucket": bucket, "key": key, "sha256": checksum, "size": path.stat().st_size}


def preview_url(receipt, run):
    bucket = os.environ.get("STUDIO_S3_BUCKET", "").strip()
    if not bucket or receipt["bucket"] != bucket:
        raise ValueError("Archive bucket does not match the current configuration.")
    expected = f"previews/{run}/{receipt['sha256']}.mp4"
    if receipt["key"] != expected:
        raise ValueError("Unexpected archive key.")
    return s3_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": expected}, ExpiresIn=120,
    )
