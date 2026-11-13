# Story Video Automation

## Run the demo

Open PowerShell in the project folder and run:

```powershell
.\run.cmd draft --demo
.\run.cmd render RUN_NAME
```

Replace `RUN_NAME` with the name printed by the first command. Open `runs/RUN_NAME/preview.mp4` to see a sample with colored frames and Bengali captions.

## Use your own story and make last-minute changes

1. Enter your story or idea in `story` in `input/brief.json`. Put last-minute instructions in `final_changes`. Use the same file to adjust the language, visual style, duration, audio, and captions. The default output is vertical 1080p.
2. Copy `.env.example` to `.env`. Set your OpenAI API key and a Responses API model available to your account, or configure the [multi-provider story router](documentation/implementation.md). FFmpeg must be available through PATH, `FFMPEG_PATH`, or Python's `imageio-ffmpeg` package. Burning captions requires FFmpeg with libass.
3. Run `.\run.cmd draft` and review `runs/RUN_NAME/plan.json`. Edit scenes, dialogue, captions, or post copy directly in the plan. To regenerate the story with new instructions, edit the brief and run `draft` again.
4. Run `.\run.cmd render RUN_NAME`. If your video service is **muse-video.com**, set `MUSE_PROVIDER=muse-video.com` and `MUSE_API_KEY`. Other Muse services require their own adapter. Regenerating edited scenes may use credits. To supply your own MP4, run `.\run.cmd render RUN_NAME --video "D:\my-video.mp4"`.
5. Review the visuals, audio, and pronunciation in `preview.mp4`. Set `made_for_kids` and `synthetic_disclosure` according to your content before uploading.

## Export resolution

`resolution` sets the Muse source to 720p or 1080p. `export_resolution` selects 720p (720×1280), 1080p (1080×1920), 1440p (1440×2560), or 4K (2160×3840). FFmpeg uses Lanczos scaling when the export exceeds the source resolution. Changing only the export resolution reuses the cached Muse clips for that run. An MP4 supplied with `--video` retains its original resolution.

## Upload and automate

For YouTube, configure a Google OAuth client with YouTube Data API enabled and a refresh token authorized for `youtube.upload`. For Facebook, set the Page ID, Page access token, and Graph API version. Keep credentials in the local `.env` file.

```powershell
.\run.cmd upload RUN_NAME --platform both
.\run.cmd upload RUN_NAME --platform both --public
.\run.cmd auto --platform both --public
```

The first command submits the video as private on YouTube and as a draft on Facebook. The second requests public publication. The third uses the current story and final instructions to generate, render, and submit the video in one run. To review the preview before uploading, use the separate `draft`, `render`, and `upload` commands.

Successful submissions are recorded per run and platform. Use YouTube Studio or Meta Business Suite to publish an existing private video or draft. If the connection drops during an upload, check the platform for the result before resubmitting. If Muse is still processing a scene, rerun `render` with the same run name to resume polling.

## Local dashboard and worker

Install Python 3.12+, FFmpeg, and the Python dependencies. From the project root, set a private admin token of at least 24 characters in the API terminal and start the server:

```powershell
python -m pip install -r requirements.txt
$env:STUDIO_ADMIN_TOKEN = 'replace-with-a-long-random-token'
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8765
```

In a second terminal, start the worker from the same folder:

```powershell
python -m backend.worker
```

Open `http://127.0.0.1:8765`, enter the admin token, and queue a demo or a real render. Pending jobs persist in the local SQLite database. If a worker stops during a paid render or an upload, inspect the provider or platform and the run receipts before resubmitting. See the [implementation checklist](documentation/implementation.md) for distributed deployment work.

- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Muse Video API](https://muse-video.com/docs/api)
- [YouTube Data API](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)
- [Facebook Reels API](https://www.postman.com/meta/facebook/request/juhnm3q/4-publish-reel)

## Configure live APIs later

The demo runs without API keys. When you have your accounts, copy the
environment template and edit the local file:

```powershell
Copy-Item .env.example .env
.\run.cmd check --platform both
```

Set the story credentials (or story router), then choose a video provider
or illustrated mode. Voice credentials are needed only if you enable TTS.
Supply the publishing credentials for the selected platforms. To prepare
one platform first, pass youtube or facebook to the check command.

The check validates local settings and FFmpeg without sending requests,
spending credits, or uploading videos. A successful check does not verify
token validity or platform permissions. For a live trial, render and review
the preview, then use the upload command without --public to submit privately
to YouTube or as a Facebook draft.

## Dashboard and distributed deployment

The Next.js dashboard supports job submission, previews, provider defaults,
scheduled deliveries, and on-demand engagement. PostgreSQL and Redis/Celery
are available through the distributed Compose configuration. See
[deployment instructions](documentation/deployment.md) for setup and acceptance checks.
