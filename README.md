# Tapo cameras: the new local protocol ("V4", SPAKE2+)

My Tapo C510W stopped talking to pytapo / python-kasa / Home Assistant after a firmware
update (fw 1.3.4). Every login attempt came back with `error_code -40211`. Discovery shows
`encrypt_type: ["4"]`, and nothing public speaks that yet.

I spent a while digging through the official Android app and poking the camera until it
answered. This repo is the result: a full write-up of the protocol and a small Python client
that really works against my camera. Same symptom has been reported on C51A 1.3.4, C220 1.4.4,
C100 1.4.3/1.5.1 and C125 1.4.2, so it is probably the same story there.

What is in here:

* [`PROTOCOL.md`](PROTOCOL.md): the spec, byte level. Long, but everything is there. Each
  statement says whether I checked it on the real camera or only read it in the app's code.
* [`tapo_v4/tapo_v4.py`](tapo_v4/tapo_v4.py): login (SPAKE2+ on P-256) and the encrypted
  `/stok=<stok>/ds` channel (AES-128-CCM). Pure Python EC math, only needs `requests` and `pycryptodome`.
* [`tapo_v4/tapo_media.py`](tapo_v4/tapo_media.py): the media port (8800). Digest auth, AES-CBC
  multipart stream, SD card clip download, snapshots, and a tiny MPEG-TS demuxer for the audio.
* [`tests/`](tests): offline tests with a fake camera and a fake media server, no hardware needed.
* [`examples/list_and_download.py`](examples/list_and_download.py): lists what is on the SD card and grabs the last clip as MP4.

## The short version

**Login** is two `POST /` calls, `pake_register` then `pake_share`. It is SPAKE2+ with the
standard RFC 9383 M and N points. The user is the literal string `admin`, the PAKE credential is
`md5_hex(cloud password)`, and the one detail that took me forever: the transcript context is
`SHA256("PAKE V1" || user_random || dev_random)`, not the raw bytes. The camera sends back a
`dev_confirm` so you can check your keys before going further.

**Requests** go to `POST /stok=<stok>/ds` as `application/octet-stream`. The body is just
`uint32_be(seq) || ciphertext || tag16`. That's it. The app also has a 24 byte "TSLP" frame
with a CRC, but that one is for its TCP transport. If you put it in front over HTTP, the camera
reads `0x01020200` as the sequence number and answers `-40401` to whatever you send. I lost a
full day on that. First `seq` is the `start_seq` from the login. Key and nonce come from
HKDF-SHA256 over the shared key (salts `tp-kdf-salt-aes128-key` and `tp-kdf-salt-aes128-iv`),
nonce is `base[0:8] || uint32_be(seq)`.

**The JSON inside must be a `multipleRequest`**, even for a single call. A bare
`{"method":"getDeviceInfo",...}` decrypts fine on the camera side and still gets refused with a
plaintext `-40209`. Also good to know: any refused `/ds` request kills the session, so log in
again before retrying.

After that, all the usual methods work like before.

**SD card download, much faster.** pytapo asks the media port for `playback`, which the camera
paces at 1x realtime and which never stops at `end_time`. The official app uses a different
request, `download`. On my Wi-Fi a 66 s clip arrives in about 7 s, full frame rate with audio,
and the camera says `stream_status: finished` when done. With `media_type: 2` the same request
returns the JPEG snapshot of a recording. There is also a nasty trap with audio/video timestamps
that I describe in the spec (use the `X-Data-PTS` header, not the TS PTS).

## Try it

```bash
pip install requests pycryptodome python-dotenv pytest
printf 'TAPO_HOST=192.168.0.50\nTAPO_CLOUD_PASSWORD=your TP-Link account password\n' > .env
python examples/list_and_download.py
python -m pytest tests -q        # no camera needed
```

```python
from tapo_v4.tapo_v4 import TapoV4
cam = TapoV4("192.168.0.50", "<cloud password>")
print(cam.get_device_info()["device_model"], cam.get_sd_status()["status"])
print(cam.search_days("20260101", "20261231"))
```

## Caveats

* Tested on one camera only (C510W hardware 2.0, fw 1.3.4 Build 260523). If you try another
  model, please open an issue and tell me how it went.
* The app has more login flavours (hashed usernames, session reuse, device certificates on
  things like robot vacuums). I wrote down what I saw in the code, but my camera did not need them.
* One media session at a time. A second one gets `-52405` ("device in use").
* This is for your own devices. Not affiliated with TP-Link.

The media port format was first documented by [pytapo](https://github.com/JurajNyiri/pytapo), thanks for that.

I also built a small web app on top of this (live view, SD card browser, animal detection):
[tapo-web](https://github.com/freeKC/tapo-web).

MIT license.
