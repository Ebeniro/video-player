# YouTube Downloader

Video preview, source quality selection, direct video download and caption exports. Built by Trelion Digital.

Production: https://trelion-youtube.vercel.app/

## Required owner setup

The hosted app now connects to Tunelio's documented media API instead of running yt-dlp on a Vercel IP. The owner must create their own provider account and add its key in Vercel's Production environment under TUNELIO_API_KEY, using Secret type. Never paste the key in chat or commit it. Redeploy after adding the variable.

Provider documentation: https://docs.tunelio.dev/docs/

On 26 October 2026, Tunelio advertises 100 one-time trial credits, no payment method required. Info costs 6 credits, download-link creation costs 10, and transcript extraction costs 6. A full info plus video plus transcript operation uses 22 credits. This is a limited trial, not a recurring unlimited free plan. No provider account, subscription or payment has been created by this project. Without the owner's key, the app returns a clear setup-required error. Do not claim live downloads work until a real file and transcript pass.

## Flow

1. Validate a public YouTube watch, Shorts or completed-live video URL.
2. Preview title and thumbnail with YouTube's public oEmbed and thumbnail endpoints.
3. Read source-specific quality options from the provider's /info response.
4. Ask /create for a signed /tunnel link. The browser downloads from the provider directly, so media bytes do not traverse Vercel's function or temporary disk.
5. Read /transcript with the selected language and preserve original timed captions for TXT and SRT exports. Automatic captions are labelled when provenance is supplied.

The server only processes small JSON requests. There is no app-imposed video duration cap. Provider plan, format and quota restrictions still apply. Keys stay server-side. Returned download URLs must be HTTPS on the documented tunelio.dev/tunnel origin and path. No proxy configuration, cookies, token harvesting or challenge bypass is included.

## Deploy

Python Vercel project, no frontend build and no third-party Python dependencies. The function serves index.html at / and API actions at /api/index. Set TUNELIO_API_KEY in Vercel before redeploying.

## Checks

Run python -m unittest discover -s tests. These fixture tests verify URL validation, missing-key errors before network access, provider authentication handling, source qualities for a four-hour video, signed-link validation and browser redirects, quota errors, and caption timestamps/provenance. They do not substitute for a live video download or transcript test.

## Prior blocker

Direct yt-dlp video requests and youtube-transcript-api captions failed from Vercel with source hosting restrictions. Updating the downloader runtime did not remove those restrictions. The chat skill is independent and remains unchanged. Public access to the production page was verified without login; Vercel protection settings remain unchanged.
