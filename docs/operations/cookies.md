# Using a YouTube cookies file

Some YouTube content requires authentication: members-only streams, age-gated videos, and (sometimes) regular content when YouTube decides your IP looks suspicious. yt-dlp can use a Netscape-format cookies file to authenticate as you.

## Export your cookies

The reliable way is a browser extension:

- **Firefox:** "cookies.txt" by Lennon Hill (or any current fork)
- **Chrome / Edge / Brave:** "Get cookies.txt LOCALLY" (look for one with no remote-server warning)

Steps:
1. Sign in to youtube.com in a browser profile **you can dedicate to concertpvr**. Don't reuse your daily browser — yt-dlp will rotate the session and your other tabs may get logged out.
2. Open the extension → export cookies for `youtube.com` → save as `cookies.txt`.
3. Verify the file starts with `# Netscape HTTP Cookie File`.

## Place the file

Put it inside the `CPVR_DATA_DIR` so it's mounted in the container:

```
/volume1/concertpvr/cookies.txt
```

## Tell concertpvr where to find it

Settings page → **yt-dlp** → **Cookies file path**. Enter the in-container path:

```
/data/cookies.txt
```

(`/data` is where the Synology bind-mount lands inside the container.)

Save. The next yt-dlp probe or recording will use the cookies. There's no test endpoint — try adding the member-only stream and see if the probe succeeds.

## Refresh cadence

YouTube's session cookies live for ~1 month. If yt-dlp starts failing on previously-working content, re-export and replace the file. The same path is re-read on each yt-dlp invocation, so no app restart is needed.

## Security notes

- Anyone with read access to `/volume1/concertpvr/cookies.txt` can sign in to YouTube as you. `chmod 600` the file.
- The `cookies.txt` is **not** in version control. The default `.gitignore` excludes the data dir.
- If you suspect compromise: sign out of YouTube on that browser profile (or use Google's "Sign out everywhere"), then re-export.
