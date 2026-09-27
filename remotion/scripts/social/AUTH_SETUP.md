# Credential Setup — TikTok / Instagram / Facebook

The Phase 2 uploaders are complete and dry-run tested. They will not perform a
real upload until you populate three JSON files. This guide covers what to
create, where it comes from, and how to verify it.

**Security:** everything under `data/` is already git-ignored, so these files
will never be committed. Do not paste tokens into chat, logs, or issue
trackers. If a token leaks, revoke the app in the provider's developer console.

---

## 0. Where things live

| Purpose | Path |
|---|---|
| Credential files | `data/tiktok_tokens.json`, `data/instagram_tokens.json`, `data/facebook_tokens.json` |
| Upload state | `data/upload_state.json` |
| Scripts | `remotion/scripts/social/` |
| Log | stdout/stderr — every script prints a JSON result on the last line |

Each credential file ships with `"_placeholder": true`. The uploaders **refuse
to make a live upload** while that flag is set, and `--dry-run` downgrades it
to a warning so you can plan before you have credentials. Delete the
`_placeholder` line once the real values are in.

---

## 1. TikTok

### Create the app
1. <https://developer.tiktok.com> → **My Apps** → **Create**.
2. Add the **Content Posting API** product.
3. Request the scopes `user.info.basic`, `video.publish`, `video.upload`.
4. Set the redirect URI to `https://localhost/` (the uploader itself never
   redirects — you do the OAuth dance once, in a browser).

### Get a user access token
TikTok uses OAuth 2.0 with PKCE:

```
GET https://www.tiktok.com/v2/auth/authorize/
      ?client_key=<CLIENT_KEY>
      &response_type=code
      &scope=user.info.basic,video.upload,video.publish
      &redirect_uri=https://localhost/
      &state=<RANDOM>
      &code_challenge=<SHA256_OF_VERIFIER>
      &code_challenge_method=S256
```

Sign in, approve, copy `code` from the redirect. Exchange it:

```
POST https://open.tiktokapis.com/v2/oauth/token/
     client_key=<CLIENT_KEY>&client_secret=<CLIENT_SECRET>
     &code=<CODE>&grant_type=authorization_code
     &redirect_uri=https://localhost/&code_verifier=<VERIFIER>
```

The response gives `access_token` (~24 h), `refresh_token` (long-lived),
`open_id`, and `expires_in`.

### Fill in the file
```json
{
  "client_key": "...",
  "client_secret": "...",
  "access_token": "...",
  "refresh_token": "...",
  "open_id": "...",
  "scopes": ["user.info.basic", "video.publish", "video.upload"]
}
```

### Gotchas
- Unaudited apps are capped at **5 posts per 24 h per user** and the videos are
  private to the user. That is normal before audit.
- `access_token` expires daily. The uploader uses the token as-is; it does not
  auto-refresh. Swap in a fresh `access_token` (keeping the same
  `refresh_token`) whenever publishing fails with 401.
- `video_info.sha256` must match the file exactly. `tiktok_upload.py` computes
  it per attempt, so a re-render is handled automatically.
- Privacy is set by `--privacy`: `public_to_all` (1), `friends` (2),
  `private` (3). Default is `public_to_all`.
- Older apps can be forced onto the v1.2 protocol with `--api-version v1`.

### Verify
```bash
python remotion/scripts/social/tiktok_upload.py barish_ki_dua --dry-run
python remotion/scripts/social/tiktok_upload.py barish_ki_dua
```

---

## 2. Instagram + Facebook (one Meta app, two token files)

Instagram and Facebook both authenticate through Meta, so create the app once
and exchange tokens twice.

### Create the app
1. <https://developers.facebook.com> → **Create App** → type **Business**.
2. Add products: **Instagram Graph API** and **Facebook Login**.
3. Settings → Basic: add your Instagram **Professional** account as a tester /
   developer, and add the **Facebook Page** it is linked to.
4. App settings → Permissions → request:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
5. **Live mode** requires App Review or you stay in Development mode, where
   only roles/admins/testers can be published to. Uploads succeed in
   Development mode but are invisible to everyone else — useful for a smoke
   test, useless as a launch.

### Instagram prerequisites
The account **must** be Business or Creator, and **must** be linked to a Page
(Settings → Account → Linked accounts). A personal account cannot receive
Reels via the API at all.

### Exchange tokens
```
# 1. app token
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?client_id=<APP_ID>&client_secret=<APP_SECRET>

# 2. long-lived user token (60 days)
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id=<APP_ID>&client_secret=<APP_SECRET>
    &fb_exchange_token=<SHORT_LIVED_USER_TOKEN>

# 3. find your IG id and Page id
GET https://graph.facebook.com/v21.0/me/accounts
    ?fields=id,name,access_token,instagram_business_account{id,username}
    &access_token=<LONG_LIVED_USER_TOKEN>

# 4. never-expiring page token (needs "Allow Live Token Extensions")
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id=<APP_ID>&client_secret=<APP_SECRET>
    &fb_exchange_token=<LONG_LIVED_USER_TOKEN>
```

`me/accounts` returns a `page_access_token` per Page and, nested, the
`instagram_business_account.id` — that is your `ig_user_id`.

### Fill in the files
`data/instagram_tokens.json`
```json
{
  "page_access_token": "<from step 3/4>",
  "ig_user_id": "<instagram_business_account.id>",
  "page_id": "<Page id>",
  "ig_username": "<username>",
  "api_version": "v21.0"
}
```

`data/facebook_tokens.json`
```json
{
  "page_access_token": "<same Page token>",
  "page_id": "<Page id>",
  "page_name": "<Page name>",
  "api_version": "v21.0",
  "reel_max_seconds": 90
}
```

### Gotchas
- Page tokens do not expire while the user token behind them is alive — but
  they die immediately if the user removes the app or changes password.
- Instagram: a container can sit in `IN_PROGRESS` for several minutes while
  Meta transcodes. `instagram_upload.py` polls up to 30 times at 20 s. If it
  times out, the container is **not** lost — re-running resumes from the
  container rather than re-uploading, provided you keep `container_id` from
  the state ledger.
- Instagram captions cannot contain clickable links.
- The uploader uses the **binary resumable** path deliberately. The
  `video_url` variant needs a publicly fetchable URL, which a local render is
  not.
- Facebook Reels cap at 90 s. Our longest render is ~26 s today, so the trim
  path rarely triggers; if a longer video ever appears, pass `--trim` to cut
  it, or `--no-trim` (the default) to fail loudly rather than silently
  shipping a clipped clip. Trimmed copies land in
  `remotion/out/_platform_trim/`.

### Verify
```bash
python remotion/scripts/social/instagram_upload.py barish_ki_dua --dry-run
python remotion/scripts/social/facebook_upload.py barish_ki_dua --dry-run
python remotion/scripts/social/facebook_upload.py barish_ki_dua --trim
```

---

## 3. Rate limits worth knowing before you batch

| Platform | Limit | Consequence when hit |
|---|---|---|
| TikTok | 5 posts / 24 h per user (pre-audit) | later posts rejected at init |
| Instagram | 25 API-published posts / 24 h rolling | `media_publish` returns an error |
| Facebook | token-scoped, effectively generous | rare |

All three uploaders retry 3 times with 1 s / 2 s backoff on 5xx, 429 and
network errors. Rate-limit rejections are surfaced into
`data/upload_state.json` as `failed` with the provider's message, so
`POST /api/v1/upload/retry/{dua_id}/{platform}` in Phase 3 can replay them.

---

## 4. What is verified vs. what is not

**Verified in this phase** (no credentials required):
- all four scripts compile and import cleanly
- `--dry-run` resolves the correct MP4 for both short and long forms
- duration probing via ffprobe, including the Title-Case long-form filenames
- caption formatting and limit enforcement per platform
- the 90 s Facebook trim path (ffmpeg invocation, caching, idempotency)
- credential validation, including the placeholder guard
- clean failure for unknown dua ids and path-traversal attempts

**Not verified — needs your accounts:**
- the actual HTTP handshakes (init / upload / publish) against live endpoints
- whether your app has the required scopes approved
- real transcoding waits and provider-side rate limits

The wire protocols follow the current published flows
(TikTok `/v2/post/publish/video/init/` + binary PUT + status fetch;
Instagram resumable container → poll → `media_publish`; Facebook
`video_reels` start → PUT → finish). If a provider has since changed an
endpoint, the failure will be explicit and recorded, not silent.
