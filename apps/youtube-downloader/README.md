# YouTube Downloader

Responsive web interface for video downloads and existing YouTube captions. Built by Trelion Digital.

Deployment: https://trelion-youtube.vercel.app

## Dependencies and research

- yt-dlp: https://github.com/yt-dlp/yt-dlp (Unlicense), installed as a dependency.
- youtube-transcript-api: https://github.com/jdepoix/youtube-transcript-api (MIT), installed as a dependency.
- imageio-ffmpeg: https://github.com/imageio/imageio-ffmpeg, for merging streams.
- Deno: official Python distribution, for yt-dlp's current runtime requirement.

No source was copied from another app. Cobalt was reviewed but not integrated because its public API requires explicit permission for third-party apps. No paid API, proxy, session cookies or DRM bypass is configured.

## Features

Public watch, Shorts and completed live URLs. Independent public oEmbed metadata lookup. Source-dependent resolutions and file sizes or labelled estimates. MP4 preferred where compatible formats exist. Existing captions with language selection, copy, TXT and SRT downloads. Temporary server files are deleted after each request.

No application-imposed video duration restriction. Live streams are excluded. Removing the former 30-minute restriction does not remove Vercel's processing duration, response and disk constraints. Downloads allocate a processing disk budget based on available space. The browser buffers files before saving. Large or long-running jobs still require an appropriate processing host.

## Deploy

Import this directory into Vercel as a Python project. Dependencies install from requirements.txt. The Python function serves index.html at the root and API actions under /api/index. No frontend build or API key is required.

## Verification

On 26 October 2026, the updated deployment passed the health check with yt-dlp 2026.10.21 and its JavaScript runtime present. Public oEmbed metadata returned a video title and channel. Live format inspection, video download and transcript retrieval each returned HTTP 502 because YouTube refused the source requests. Downloads are NOT working. No working download or transcript should be claimed from a page load, mocked tests or a health check.

The production page returned HTTP 200 without cookies or sign-in. Vercel protection settings were left unchanged after automatic approval review rejected a requested setting change. Public access currently needs no protection change. The source-retrieval block is separate from page access.

## Checks

Install requirements.txt and run: python -m unittest discover -s tests

Tests use fixtures and do not claim live YouTube retrieval succeeded.
