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

This deployment uses the SQLite worker and a single Docker host. The
distributed PostgreSQL, Redis and Celery deployment remains to be implemented.
