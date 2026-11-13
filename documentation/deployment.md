# Single-host container deployment

Copy .env.example to .env and supply a random STUDIO_ADMIN_TOKEN of at least
24 characters. Keep the token and provider credentials out of source control.
For a demo, no external API credentials are necessary. For real renders, fill
in the chosen provider and publishing settings. Leave FFMPEG_PATH empty in
the containers so the worker uses the bundled Linux FFmpeg executable.

From the project root, run:

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f worker
```

Open http://127.0.0.1:8765 on the Docker host. The API binds to host loopback.
For remote access, use an authenticated HTTPS reverse proxy or a private
network with restricted access. The API and worker share a Docker volume for
job records, previews and receipts. Keep the volume when upgrading.

To back up, stop both services and take a snapshot of the studio-data volume.
Preserve environment and provider settings separately. Restore them together
and confirm that jobs and previews are visible before enabling uploads.
Check for interrupted paid requests and submissions with the provider before
resubmitting them.

This deployment uses the SQLite worker and a single Docker host. See the distributed deployment below for the PostgreSQL option.


## PostgreSQL, Redis, and Celery

Set STUDIO_DB_PASSWORD in the local .env. Set STUDIO_DATABASE_URL to a
PostgreSQL connection URI such as postgresql://studio:PASSWORD@db:5432/studio
with the same password URL-encoded. Start the services with:

    docker compose -f compose.yaml -f compose.distributed.yaml up --build -d

The application creates the required tables on first connection. Use a new
database or migrate existing SQLite records separately. Redis is an internal
Celery broker. Run one beat instance to dispatch jobs and due uploads.
The database claim guards prevent a duplicate dispatch from starting the
same row twice. Interrupted provider requests still require reconciliation.
Keep the media volume on the same Docker host as workers and the API.

## Next.js dashboard

From the project root, run npm ci, npm run build, and npm run start.
The dashboard runs on port 3000 and proxies API requests to port 8765.
Set STUDIO_API_URL before the build if FastAPI uses a different address.
The admin token stays in page memory. The classic dashboard remains on
the FastAPI port.

The Next.js build and local SQLite test suite were verified on Windows.
Run Compose and verify PostgreSQL, Redis, Celery, and a demo render on a
Docker host before deploying with live API credentials.

## Asset archive and worker status

Set STUDIO_S3_BUCKET to enable private preview archiving for real studio
jobs. Use the AWS SDK credential chain, a private bucket, and an identity
authorized to write its previews prefix. Set STUDIO_S3_ENDPOINT for an
S3-compatible service. The local preview remains the upload source.
The archive receipt records the object key, size, and SHA-256 digest.
Apply retention rules in the bucket configuration.

Authenticated GET /api/operations returns queue totals and seconds since
each worker last entered its queue loop. A worker processing a long job
can have an older timestamp. Use container health and queue state together.
