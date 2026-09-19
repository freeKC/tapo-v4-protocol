# PROTOCOL.md - Tapo C510W local protocol: control API ("V4" / TPAP) + media port 8800

> **Note for readers of the public copy.** This spec was written inside a private project. Paths such as
> `~/tapo-web/...`, `app/sd.py`, `TESTS.md` or `_spikes/decompiled` refer to the author's own web app, test log and
> decompiled copy of the official Android app (Tapo 3.21.111) - they are not part of this repository. The two
> reference clients (`tapo_v4/tapo_v4.py`, `tapo_v4/tapo_media.py`) and the offline tests are. IP/MAC/ids are placeholders.

Exhaustive, self-sufficient, byte-exact specification of how to talk **locally** to a
TP-Link Tapo **C510W, firmware `1.3.4 Build 260523 Rel.33481n`**: discovery, login,
the encrypted control channel, every SD-card / playback related control method, the
media port (thumbnails, clip download, playback, teardown) and how to turn the
stream into an MP4. Live video does **not** need any of this - it uses RTSP (see
`ENVIRONMENT.md`).

Status date: **2026-09-18**. No secret is written in this file: credentials live in
`.env` (perms 600) - see §2.

---

## 0. Overview & status legend

### 0.1 Status legend - every statement carries one of these

| Tag | Meaning |
|---|---|
| ✅ | **Verified live** against the real camera (C510W fw 1.3.4): on 2026-09-18 unless the statement cites `TESTS.md` A/B, which records the earlier live session (same camera, same firmware). Items that come from that earlier session: `-40209` for an e-mail username, "any other credential hashing fails", `-40211` for V3-shaped logins, `-40421` for a percent-encoded stok, no `Set-Cookie`. |
| 📖 | **From app code, not tested live**: read in the decompiled official app *Tapo Android 3.21.111*. Citations are `file:line`. |
| 🌐 | Public prior art (pytapo, python-kasa PR #1592, Depau's notes…), not re-tested here. |
| 🧪 | Offline analysis of streams **captured live from this camera** (TS parsing, ffmpeg tests on files). |

Citation convention: `D = ~/tapo-web/_spikes/decompiled`. A bare path such as
`hm1/a0.java:175` means `D/src4/sources/hm1/a0.java`. Other trees are prefixed
(`src3/`, `src5/`, `src6/`, `full/`, `full9/`, `full13/`…, all under `D`, all with a
`sources/` directory). The same obfuscated class can exist in several trees with
different line numbers; the tree given is the one the line numbers belong to.

### 0.2 The two channels

```
                        ┌────────────── control API ──────────────┐
 UDP 20002 discovery →  │ HTTPS 443, self-signed cert CN=TPRI-DEVICE│
                        │  POST /            JSON  login (SPAKE2+)  │  §3 §4
                        │  POST /stok=<stok>/ds   AES-128-CCM       │  §5 §6
                        └──────────────────────────────────────────┘
                        ┌────────────── media port ───────────────┐
                        │ TCP 8800, plain HTTP-like, long-lived     │
                        │  POST /stream  multipart/mixed both ways  │  §7
                        │  Digest auth → Key-Exchange → AES-128-CBC │
                        │  payload = MPEG-TS (H.264 + G.711 A-law)  │  §8
                        └──────────────────────────────────────────┘
```

- The camera advertises encryption scheme **"V4"** (`encrypt_type: ["4"]`). In the
  app's vocabulary this is **TPAP** (session classes named "TLA", session type string
  `"SPAKE2+"`): a **SPAKE2+** password-authenticated key exchange (P-256, SHA-256,
  HKDF, PBKDF2) done as a two-step JSON handshake, then an **AES-128-CCM**
  request/response channel. ✅
- V3 clients (pytapo, released python-kasa) cannot log in: they get `-40211`. ✅
- The two channels are independent: the media port authenticates with its own HTTP
  Digest + key exchange and needs **no** `stok`. The only things the media port takes
  from the control API are the clip boundaries (`startTime`/`endTime`). ✅
- Both need the **cloud account password** (differently hashed). ✅ value/hashing - 📖 that
  it is the cloud (not camera-account) password, see §2.

### 0.3 Reference implementation (ground truth for everything marked ✅)

| File | Role |
|---|---|
| `tapo_v4/tapo_v4.py` | control API client: pure-Python P-256, SPAKE2+, `/ds`, SD listing helpers |
| `tapo_v4/tapo_media.py` | media port client: auth, AES, multipart, acks, `download` request, TS demuxer |
| `~/tapo-web/app/sd.py` | how the web app uses both (serialised media sessions, thumbnails, ffmpeg HLS+MP4) |
| `~/tapo-web/tests/` | offline regression tests (fake camera for `/ds`, fake "Streamd" for 8800, synthetic TS) |

---

## 1. Discovery (confirms V4) - UDP 20002

✅ `python-kasa`'s discovery reaches the camera and returns its advertisement.
Example result (real, from this camera):

```json
{
  "device_type": "SMART.IPCAMERA", "device_model": "C510W",
  "ip": "192.168.0.50", "mac": "AA-BB-CC-DD-EE-FF",
  "mgt_encrypt_schm": { "is_support_https": true },
  "encrypt_type": ["4"],
  "decrypted_data": { "http_port": 443, "sd_status": "normal", ... },
  "firmware_version": "1.3.4 Build 260523 Rel.33481n"
}
```

`encrypt_type: ["4"]` + no `tpap` object ⇒ **V4 over HTTPS on 443**, and
`sd_status: "normal"` ⇒ the SD card is present and healthy. Reproduce with:

```python
import asyncio
from kasa import Discover, Credentials
async def main():
    d = await Discover.discover_single("192.168.0.50",
            credentials=Credentials("<TAPO_USER>", "<CAMERA_PASSWORD>"))   # what was run; values in .env
    print(d._discovery_info)
asyncio.run(main())
```

Other ways to find the camera:

- ✅ Scan the LAN for a TLS certificate with `CN=TPRI-DEVICE` on 443 plus an open RTSP
  port 554 (this is what `app/camera.py` does; reliable).
- ✅ Open ports on this camera: 443 (control), 554 (RTSP), 2020 (ONVIF), 8443, 8800
  and 28800 (media). 📖 28800 is the TLS-PSK variant of the media port used by the
  app's pre-connection client (`src6/o91/l.java:62,122-129`); never used here.

📖 What the official app expects from discovery (not observed on this camera through
python-kasa - open question, see §12.3):

- The app takes the TPAP path **only** when the TDP discovery result carries a
  top-level `tpap` object: `{tls, dac, noc, pake:[…], port, user_hash_type, owner}`
  (`lu0/yj.java:112-128`, `pu0/i1.java:39-41`, `u11/a.java:6-25`,
  `TDPTpapInfo.java:7-15`). Otherwise it uses `LocalSecureSession` for
  `encrypt_type == ["3"]`, or a plain session.
- Base URL = `"https://" + ip + ":" + port`, with `port = tpap.port` if `> 0`, else the
  TDP `http_port` (443) (`transport/local/d2.java:86-100`).
- `tpap.pake` selects `passcode_type`: `2 → "userpw"`, `1 → "setupcode"`,
  `0 → "default_userpw"`, `3 → "shared_token"` (`j2.java:244-265`, an `else if` chain in
  that priority order - details and the passcode of each type in §4.1);
  `tpap.user_hash_type` selects the username hash (§4.1).
- 🌐 python-kasa PR #1592 obtains the same object with
  `POST /  {"method":"login","params":{"sub_method":"discover"}}`. Not tested on this camera.
- 🌐 A public fixture of another V4 camera (C101 hw5.0 fw 1.4.3) shows
  `tpap: {noc:1, pake:[2], port:443, tls:1}`.

---

## 2. Credentials

**No literal secret in this file.** All values are in `.env`:

| `.env` key | Placeholder used below | What it is |
|---|---|---|
| `TAPO_HOST` | `<ip>` | camera IP (`192.168.0.50`, reserved lease) |
| `TAPO_CLOUD_USER` | `<TAPO_CLOUD_USER>` | TP-Link cloud account e-mail |
| `TAPO_CLOUD_PASSWORD` | `<CLOUD_PASSWORD>` | TP-Link cloud account password |
| `TAPO_USER` | `<TAPO_USER>` | "camera account" user (RTSP / ONVIF only) |
| `TAPO_PASSWORD` | `<CAMERA_PASSWORD>` | "camera account" password (RTSP / ONVIF only) |

| Purpose | Value |
|---|---|
| Camera "V4" handshake username | **`admin`** (literal; the account e-mail does NOT work here → error `-40209`) ✅ |
| Camera "V4" handshake password source | the **cloud account password** `<CLOUD_PASSWORD>` (confirmed valid by a cloud login, see `TESTS.md` A3) ✅ |
| **PAKE credential fed to PBKDF2** | **`md5_hex(cloud_password)`** = `hashlib.md5(b"<CLOUD_PASSWORD>").hexdigest()` (lowercase hex) ✅ |
| Media port 8800 Digest user / password | `admin` / `SHA256(cloud_password).hexdigest().upper()` (§7.2) ✅ |
| RTSP / ONVIF ("camera account") | `<TAPO_USER>` / `<CAMERA_PASSWORD>` ✅ |
| Cloud account | `<TAPO_CLOUD_USER>` / `<CLOUD_PASSWORD>` ✅ |

⚠ On this installation `TAPO_PASSWORD` and `TAPO_CLOUD_PASSWORD` hold the **same string**
(compared programmatically, values never printed), so the live tests prove the *value* and the
*hashing* (✅) but cannot tell which account's password the camera checks - neither for the
PAKE credential nor for the 8800 Digest. That it is the **cloud** account password is 📖 (the
app provisions the camera's PAKE verifier from `md5hex(<account password>)`:
`pu0/i1.java:94-111`; and logs in with `h = rb1.a.h(dVar.d())`, `j2.java:241-245`) and 🌐
(pytapo uses the cloud password for port 8800). If the two ever differ, use the cloud password.

✅ The PAKE "password" is **not** the raw text password - it is the lowercase MD5 hex
digest of the cloud account password. This was verified: any other hashing (raw,
SHA-256, uppercase) fails, and MD5-hex is what makes `dev_confirm` match.

📖 Why MD5-hex: the app itself provisions the camera's PAKE verifier from
`md5hex(cloud password)` with a 16-byte random salt and 5000 iterations
(`pu0/i1.java:94-111`, `LocalCtrlParams.java:8-31`) - consistent with the observed
16-byte `dev_salt` and `iterations: 5000`.

---

## 3. SPAKE2+ constants and primitives (P-256)

✅ (all of §3; proven by `dev_confirm` matching live)

- Curve: **secp256r1 / P-256**. `p`, `n` (order), `G` = standard.
- SPAKE2+ seed points (standard, RFC 9383 values), given as compressed hex:
  ```
  M = 02886e2f97ace46e55ba9dd7242579f2993b64e16ef3dcab95afd497333d8fa12f
  N = 03d8bbd6c639c62937b04d997f38c3770719c629d7014d49a24b4f98baa1292b49
  ```
  Decompress them to full points before use. (Same constants in the app: `kl1/d.java:11-12`.)
- Point encoding on the wire: **uncompressed SEC1** = `0x04 || X(32) || Y(32)` = 65
  bytes, then **base64**.
- `H(x)` used in the transcript hash and confirmations = plain SHA-256.
- Length-prefix in the transcript = **8-byte little-endian** length before each
  element.

The reference implementation `tapo_v4.py` contains a self-contained, tested
pure-Python P-256 (point add / scalar-mul / (de)compress). Its correctness is
verified two ways: the SPAKE2+ prover/verifier invariant (both sides derive the
same Z and V) holds, and the live `dev_confirm` matches.

For reference, the curve parameters used by `tapo_v4.py`:
```
p  = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
a  = p - 3
b  = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
n  = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
Gx = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
Gy = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
```

---

## 4. Login handshake - `POST /` with JSON `{"method":"login","params":{…}}`

✅ Two round-trips; the reference does them on the **same** keep-alive HTTPS connection
(one `requests.Session`). 📖 The app uses a fresh connection for each (§4.7), so one
connection is not required - not tested live. TLS: accept the self-signed certificate
(`CN=TPRI-DEVICE`) without verification. HTTP/1.1.

Headers the reference client sends on login (✅ works):
```
Content-Type: application/json
Referer: https://<ip>:443:443        (sic - reference quirk, see §5.5; the app sends https://<ip>:443)
User-Agent: Tapo CameraClient Android
requestByApp: true
(+ python-requests defaults: Host, Accept: */*, Accept-Encoding, Connection: keep-alive, Content-Length)
```
The app's exact header set is in §5.5. The top-level body is exactly
`{"method":"login","params":{...}}`; key order and JSON spacing do not matter ✅ (the
reference sends `json.dumps` default spacing on login and it works).

### 4.1 pake_register

✅ Request body (exactly what works):
```json
{"method":"login","params":{
  "sub_method":"pake_register",
  "username":"admin",
  "user_random":"<base64(32 random bytes)>",
  "cipher_suites":[1],
  "passcode_type":"userpw"
}}
```
✅ Response (`error_code: 0`), `result` fields:
- `iterations` - PBKDF2 iteration count (observed **5000**).
- `dev_salt` - base64, **16 bytes**, constant per device (`<base64, 16 bytes>`).
- `dev_random` - base64, 32 bytes, fresh each call.
- `dev_share` - base64, the device SPAKE2+ share **Y** (uncompressed P-256 point).
- `encryption` - the negotiated session cipher, `"aes_128_ccm"` (returned even though
  the request carries no `encryption` field).
- `cipher_suites` - `1`.

📖 **What the official app sends instead** (all variants; none needed on this camera).
Params class `Spake2pRegisterParams` (`com/tplink/tls/codec/spake2p/bo/Spake2pRegisterParams.java:7-22,84-99`),
built at `em1/a.java:125-134`; Gson with HTML-escaping disabled, **null fields omitted**
(`com/tplink/tls/session/f.java:6`):

| JSON key | App value | Source |
|---|---|---|
| `sub_method` | `"pake_register"` | `Spake2pBean.java:26` |
| `username` | **never the literal `admin`**: `md5hex("admin")` lowercase = `21232f297a57a5a743894a0e4a801fc3` when `tpap.user_hash_type == 0`/absent; `SHA256("admin")` UPPER hex = `8C6976E5B5410415BDE908BD4DEE15DFB167A9C873FC4BB8A81F6F2AB448A918` when `user_hash_type == 1` | `transport/local/j2.java:276-283`, `pu0/i1.java:82`, `rb1/a.java:79-92`, `util/k.java:115-129` |
| `user_random` | base64 of 32 `SecureRandom` bytes | `session/f.java:8-12` |
| `cipher_suites` | `[1]` | `j2.java:242` |
| `encryption` | `["aes_128_ccm"]` (list of ciphers the client accepts) | `j2.java:120`, `session/e.java:35-37,297`, `em1/a.java:128,134` |
| `passcode_type` | `"userpw"` (pake 2) / `"setupcode"` (1) / `"default_userpw"` (0) / `"shared_token"` (3) | `j2.java:244-265` |
| `auth_type` | only kept when `passcode_type == "setupcode"` | `Spake2pRegisterParams.java:94-99` |
| `stok` | the **previous** stok, only on re-login while a session cipher is still held (session reuse, §4.7) | `em1/a.java:131-133` |

📖 Priority and passcodes (`j2.java:239-265`, an `else if` chain - first match wins):
`tpap.pake` contains **2** → `"userpw"`, passcode candidates of §4.5; else **1** →
`"setupcode"`, passcode = the setup code transformed by `util.h.p(code)` (transform not
analysed) with `auth_type` set, or `gm1.a.b(mac)` when the app holds no setup code; else
**0** → `"default_userpw"`, passcode = `gm1.a.b(mac)`; else **3** → `"shared_token"`, passcode =
`md5hex(cloud password)` (the same `h` as the first userpw candidate). `cipher_suites` is `[1]`
in every case. `gm1.a.b(mac)` (`gm1/a.java:14-30`) is a MAC-derived default: strip `:`/`-` from
the MAC and hex-decode it to 6 bytes `m`; `ikm = "GqY5o136oa4i6VprTlMW2DpVXxmfW8" (30 ASCII bytes)
‖ m[3:6] ‖ m[0:3]`; result = UPPER hex of `HKDF_SHA256(ikm, salt="tp-kdf-salt-default-passcode",
info="tp-kdf-info-default-passcode", L=32)`. None of the non-`userpw` types was tested.

App-exact first-login body (compact JSON; key order inferred from Gson reflection, irrelevant to the camera):
```json
{"method":"login","params":{"cipher_suites":[1],"encryption":["aes_128_ccm"],"passcode_type":"userpw","user_random":"<b64 32B>","username":"21232f297a57a5a743894a0e4a801fc3","sub_method":"pake_register"}}
```
🌐 python-kasa PR #1592 and ioBroker.tapo send the same plus `"stok":null`.

📖 Extra `result` fields the app reads (`Spake2pRegisterResult.java:7-25`):
`extra_crypt {type, params{authkey_dictionary, authkey_tmpkey, passwd_id, passwd_prefix,
passwd_rounds, passwd_salt, sha_name, sha_salt}}` (§4.5), `iterations` (app default
10000 when absent), `expired` (if `> 0` ⇒ stok reuse, §4.7). Error envelope
(`TslpAuthResponse.java:7-13`): `error_code | err_code`, `error_info | err_msg`, `msg`,
`result`; `error_info = {failedAttempts, lockedMinute, remainAttempts}`.

### 4.2 Derive keys (client side, no network)

✅
```
credential = md5_hex(cloud_password)                 # utf-8 string, lowercase hex
dk  = PBKDF2_HMAC_SHA256(credential.utf8, dev_salt, iterations=5000, dkLen=80)
w0  = int(dk[0:40],  big) mod n
w1  = int(dk[40:80], big) mod n
x   = random scalar in [1, n-1]
X   = x*G + w0*M                                      # user_share (uncompressed)
Y   = decode(dev_share)
Hp  = Y - w0*N ;  Z = x*Hp ;  V = w1*Hp

context = SHA256( b"PAKE V1" || user_random_bytes || dev_random_bytes )   # 32 bytes
# NOTE: the transcript uses the SHA-256 of the context, NOT the raw bytes. This
# was the single most important detail to get the handshake to pass.

TT = lv(context) || lv("") || lv("") || lv(M_unc) || lv(N_unc)
        || lv(X_unc) || lv(Y_unc) || lv(Z_unc) || lv(V_unc) || lv(w0_be32)
     # lv(b) = little_endian_uint64(len(b)) || b
     # idProver and idVerifier are BOTH empty strings.
     # w0_be32 = w0 as 32-byte big-endian.

Ke  = SHA256(TT)
KcA || KcB = HKDF_SHA256(IKM=Ke, salt=None(→32 zero bytes), info=b"ConfirmationKeys", L=64)
SharedKey  = HKDF_SHA256(IKM=Ke, salt=None(→32 zero bytes), info=b"SharedKey",        L=32)

user_confirm  cA = HMAC_SHA256(KcA, Y_unc)
expected_devC cB = HMAC_SHA256(KcB, X_unc)
```
Use the `iterations` value returned by the camera (5000 here), not a constant.

📖 Code pointers: PBKDF2 → 2×40-byte halves `jl1/d.java:9-14`; context hashed before
use `em1/b.java:36-40,67`; transcript and 8-byte LE length prefix `jl1/a.java:36-49,56-60,69-78`;
**`w0` is encoded at fixed curve-order length (32 bytes)**, `jl1/a.java:46`; key schedule
`jl1/a.java:24-33` + `kl1/k.java:26-37`. 🌐 python-kasa PR #1592 encodes `w0` at
*minimal* length instead (`tpaptransport.py:408-416`) - that differs from the app
whenever `w0 < 2^248`; follow the app / this spec (fixed 32 bytes).

### 4.3 pake_share

✅ Request body:
```json
{"method":"login","params":{
  "sub_method":"pake_share",
  "user_share":"<base64(X_uncompressed)>",
  "user_confirm":"<base64(cA)>"
}}
```
✅ Response (`error_code: 0`), `result` fields:
- `stok` - the **session token** (32 chars; can contain `! * ( ) ~` etc. - send it
  raw in the URL, do **not** percent-encode it).
- `start_seq` - the session sequence base (int; observed values such as `55456171`,
  `68595236`, `74287929`, i.e. positive 32-bit ✅; 📖 it is a **signed** Java `Integer`
  in the app, so handle negative values as in §5.1).
- `expired` - session lifetime (observed `3600`).
- `dev_confirm` - base64. **Must equal `cB` above.** It does - this proves the
  session keys match the camera. (If it ever does not match, the credential or a
  crypto step is wrong.)

📖 App-only: `dac_nonce` is added to the request only for devices with DAC attestation
(`em1/a.java:37-44,94-97`); never for cameras (`j2.java:272-274` passes `null`). Extra
result fields the app reads: `dac_ca`, `dac_ica`, `dac_proof` (`Spake2pShareResult.java:5-18`).

### 4.4 Session cipher keys (client side)

✅
```
realKey   = HKDF_SHA256(IKM=SharedKey, salt=b"tp-kdf-salt-aes128-key", info=b"tp-kdf-info-aes128-key", L=32)[0:16]
realNonce = HKDF_SHA256(IKM=SharedKey, salt=b"tp-kdf-salt-aes128-iv",  info=b"tp-kdf-info-aes128-iv",  L=32)[0:12]
```
Per-message CCM nonce for a given `seq` (int): `realNonce[0:8] || big_endian_uint32(seq)`.

✅ The HKDF digest for session key/nonce is **SHA-256** (RFC 5869 extract-then-expand;
`salt=None` ⇒ 32 zero bytes). Asking HKDF for `L=16`/`L=12` directly gives the same
bytes as `L=32` truncated (block T(1) does not depend on L).
📖 `SecSessionCipher.java:10-24`, `SecEncryptor.java:6,116-124,157-177`; SHA-256 proven at
`full9/org/bouncycastle/crypto/util/a.java:113-115` → `full9/ft1/h.java:64-75`;
HKDFParameters order (ikm, salt, info) `full9/pt1/g0.java:44-46`. The cipher is chosen
from the `encryption` string of the **register result** (`em1/a.java:112`).

### 4.5 Credential derivation variants 📖 (not needed here: this camera returns no `extra_crypt`)

`Spake2pRegisterResult.getSpake2pCredentials(user, passcode, mac)` (`Spake2pRegisterResult.java:64-77`,
`Spake2pExtraCryptBean.java`):

- No `extra_crypt`: credential = `user + "/" + passcode` if `user != null`, else `passcode`.
  For **cameras** `user` is `null` (`j2.java:272-274`) ⇒ credential = passcode alone.
  (For TP-Link IoT plugs/bulbs it is `"<account e-mail>/<raw password>"`, §5.8.)
- Passcode candidates the camera path tries in order, moving on at any failure incl. a
  `dev_confirm` mismatch (`j2.java:244-250`, `em1/a.java:165-192`):
  1. `md5hex_lower(cloud password)` ← the one that works ✅
  2. `SHA256_HEX_UPPER(localAccessToken "lat")`, if the app has one
  3. `SHA256_HEX_UPPER(cloud password)`
- `extra_crypt.type == "password_shadow"`: by `passwd_id` - `1`: md5-crypt (`$1$`) of the
  passcode with `passwd_prefix`; `2`: `sha1hex(passcode)`; `3`: `sha1hex(md5hex(username) + "_" + MAC "AA:BB:…" upper)`
  only when username non-null; `5`: sha256-crypt (`$5$`, body not decompiled)
  (`Spake2pExtraCryptBean.java:85-177,192-198,255-269,353-369`).
- `"password_authkey"`: `authKey(passcode, authkey_tmpkey, authkey_dictionary)`, an XOR/index scheme (`:52-73`).
- `"password_sha_with_salt"`: `sha256hex(("admin" if sha_name==0 else "user") + str(b64decode(sha_salt)) + passcode)` (`:331-342`).
- `isCompatibleCipher = (extra_crypt != null)`, `isWeakCipher = (passwd_id == 3)`: they only
  trigger a UI "sync password" flow, not a different data cipher (`Spake2pRegisterResult.java:79-92`, `j2.java:328-350`).

### 4.6 NOC / DAC branches 📖

- If `tpap.noc == 1` **and** a user NOC certificate is cached, the app tries NOC
  (certificate) authentication first and falls back to SPAKE2+ on failure
  (`j2.java:208-220`, `session/e.java:301-305`, `hm1/a0.java:33-57` "Falling back to
  SPAKE2P due to NOC failure"). The data channel afterwards is identical.
- DAC attestation (`dac_nonce` / `dac_proof`) only when a discover bean exists, a DAC
  cert is configured and `tls == 0 && dac == 1`; never for cameras. No `discover`
  sub_method is sent by the camera path (`em1/a.java:70-79`).
- ✅ On this camera neither branch is needed: plain `pake_register` → `pake_share` works.

### 4.7 Session lifetime, binding and reuse

- ✅ `expired: 3600` s. The reference re-logs in 60 s before expiry (`logged_in()`).
- ✅ Login and `/ds` work on one keep-alive connection (what the reference does), and no
  `Set-Cookie` is ever returned (`TESTS.md` B2): there is no cookie mechanism.
- 📖 The session is not bound to a TCP/TLS connection: the app sends each login POST through
  an OkHttp client with `ConnectionPool(0 idle)` (a fresh connection per POST) and `/ds`
  through a *different* pooled client (`lu0/yj.java:88-97,111-123`, `pu0/o.java:230,261`); its
  cookie jar is a no-op (`ou0/a.java:14-21`). Using separate connections was not tested live here.
- ✅ A session **dies** as soon as the camera refuses a `/ds` body (§5.3). Log in again.
- 📖 **stok reuse**: on re-login with a live cipher the app adds `"stok":"<old stok>"` to
  `pake_register`; if the reply has `expired > 0` it **skips `pake_share`**, keeps the old
  cipher and resets its counter to the **original** `start_seq` (`em1/a.java:87-90,131-133`,
  `hm1/a0.java:158-164,205-213`). Not tested.
- 📖 Nothing is sent right after login (no component negotiation); the session is active
  once `dev_confirm` matches (`hm1/a0.java:59-86,186-203`).

### 4.8 Login failures

| Reply | Meaning |
|---|---|
| `-40209` on `pake_register` | unknown username (e.g. the account e-mail) ✅ |
| `-40211` | the request was V3-shaped (`cnonce`, `encrypt_type:"3"`, KLAP, RSA, legacy MD5…) - the camera is V4 only ✅ |
| `pake_share` returns an `error_code` instead of a `result`, **or** `dev_confirm` ≠ `cB` | wrong credential or crypto slip. The reference raises `TapoV4Error(<code>, "pake_share failed")` / `TapoV4Error(0, "dev_confirm mismatch")` (`tapo_v4.py` `login()`). Which of the two this camera produces for a wrong password was **not recorded**. 📖 The app treats either as "try the next passcode candidate" (`em1/a.java:165-192`); failed attempts are counted (`error_info.failedAttempts / remainAttempts`, `TslpAuthResponse.java:7-13`), so do not brute-force variants. |
| `-40404` / `-40408` | device / system **locked** after too many bad logins. Codes exist; ✅ not triggered here. Back off for minutes. 📖 `error_info.lockedMinute / remainAttempts` tell how long |

---

## 5. Encrypted control channel - `POST /stok=<stok>/ds`

**✅ Working.** 📖 Source of truth: the app's HTTP authenticator `hm1/a0.java` (`b()` builds
the request :171-180, `o()` parses the reply :291-298) + `com/tplink/security/cipher/SecSessionCipher.java`.

### 5.1 Request

```
POST /stok=<stok>/ds HTTP/1.1            # stok RAW in the path, no query string
Content-Type: application/octet-stream
Accept: application/octet-stream
(+ Referer / User-Agent / requestByApp, §5.5)

inner = compact_json({"method":"multipleRequest",
                      "params":{"requests":[{"method":<m>,"params":<p>}, ...]}})     # UTF-8
seq   = start_seq            # FIRST request uses start_seq itself (AtomicInteger.getAndIncrement),
                             # then +1 for every request sent (failed ones included)
ct,tag = AES_128_CCM(realKey, nonce = realNonce[0:8] || uint32_be(seq), inner, tag_len=16, aad=None)
body   = uint32_be(seq) || ct || tag          # that is ALL: no TSLP header, no CRC, no base64
```

Sequence rules:
- ✅ first `seq = start_seq`, then `+1` per request; the 4-byte prefix **must equal** the seq used in the nonce.
- ✅ A first request with `seq = start_seq + 1` was **also accepted** (it decrypted: a bare method then got `-40209`). So small forward jumps are tolerated.
- 📖 Every attempt burns one seq, failed or not (`hm1/a0.java:175`). TP-Link's IoT transport persists `start_seq + 60` and reloads with `+20` (`IoTTpapTransport.java:214-225,537-544`), which suggests the device only requires a seq that keeps increasing - inference, not tested. Never reuse or decrease a seq.
- `seq` is a **signed 32-bit** Java int in the app (`Integer start_seq`, `AtomicInteger`,
  `ByteBuffer.putInt`: `hm1/a0.java:158-164,175-179`) 📖. On the wire and in the nonce it is its
  4-byte two's-complement big-endian form: use `seq & 0xFFFFFFFF` before packing (reference:
  `tapo_v4.py` `_nonce()` and `_ds()`, `struct.pack(">I", seq & 0xFFFFFFFF)`), both for a negative
  `start_seq` and on wrap-around. Only positive values were observed ✅.
- One request at a time per session (the reference holds a lock around seq allocation + POST).
- CCM: 12-byte nonce, 16-byte tag, **no associated data**, tag appended after the ciphertext. 📖 BouncyCastle `CCMBlockCipher` over AES, mac 128 bits, AAD `null` (`SecEncryptor.java:116-124`, `full9/mt1/d.java`).

Two rules that cost a day:

1. ✅ **No 24-byte TSLP frame.** The camera reads the first 4 body bytes as the sequence
   number. A TSLP header (`01 02 02 00 …`) is parsed as seq `0x01020200` → `-40401`.
   (That is why *every* variation in the old test matrix returned `-40401`.) See §5.7.
2. ✅ **The inner request must be a `multipleRequest`.** A bare
   `{"method":"getDeviceInfo",…}` decrypts fine but is refused with plaintext `-40209`
   (`INVALID_ARGUMENTS`). 📖 The app wraps ~540 of its ~550 request builders this way
   (`lu0/dk.java:2341-2343` T5, `:2392-2394` U5, `:2467-2469` V5).

Byte-exact smoke-test plaintext (128 bytes):
```
{"method":"multipleRequest","params":{"requests":[{"method":"getDeviceInfo","params":{"device_info":{"name":["basic_info"]}}}]}}
```

### 5.2 Reply

✅ HTTP 200, same layout: `uint32_be(seq) || ct || tag`, decrypted with the nonce built from
the **reply's own** seq prefix (observed equal to the request seq). Plaintext JSON:

```json
{"result":{"responses":[{"method":"getDeviceInfo","result":{…},"error_code":0}]},"error_code":0}
```
There is **one `error_code` per sub-request** inside `result.responses[i]` plus one at top
level; check both. Responses come back in request order. 📖 The app decrypts with the
prefix value rather than assuming an echo (`hm1/a0.java:291-298`) and parses
`Response<MultipleResponse>` (`transport/local/z2.java:84-87`).

### 5.3 Refusals - a **plaintext** JSON body (HTTP 200, 21 bytes) means the request was refused

| Plaintext reply | Meaning (✅ verified live unless noted) |
|---|---|
| `{"error_code":-40401}` | wrong seq **or** undecryptable payload (random bytes, TSLP frame in front…). **The session is now dead camera-side: every later request on that stok fails too** - log in again. |
| `{"error_code":-40209}` | decrypted OK, but the inner JSON shape is not accepted (not a `multipleRequest`) |
| `{"error_code":-40421}` | the stok in the URL is not accepted as a token. ✅ Observed only for a **percent-encoded** stok (earlier session, `TESTS.md` B2). ⚠ In the same test a *garbage 32-char* stok returned **`-40401`**, not `-40421`, so expect `-40401` for an unknown/expired but well-formed stok. 📖 App name: `TPAP_SESSION_TOKEN_INVALID` (`common/CameraErrorCode.java:32`). |

Detection rule used by the reference: if the body starts with `{` it is a refusal; else
it must be at least `4 + 16` bytes and authenticate under CCM (a tag failure on a reply is
treated as fatal).
Caveat: `{` is `0x7B`, so an encrypted reply whose seq lies in `0x7B000000…0x7BFFFFFF` also
starts with `{` (`start_seq` is an arbitrary 32-bit value; the observed ones were < 2^27). A
robust client does what the app does 📖 (`pu0/o.java:154-179`): try to parse the **whole** body
as a JSON object carrying `error_code`; only if that fails, treat it as
`uint32_be(seq) ‖ ct ‖ tag` (`hm1/a0.java:291-298`). Refusals seen live are exactly 21 bytes.

📖 The app recognises only `-40401` (`SESSION_EXPIRED`) and `-40421`
(`TPAP_SESSION_TOKEN_INVALID`) as plaintext session errors on `/ds` (`pu0/o.java:154-179,215-220`);
its transport treats `-40401, -40420, -40421, -40418, -2402` as "token expired → re-login"
(`transport/local/x0.java:940-951`). `-40420 = TPAP_SLP_AUTH_TAG_SIG_FAIL` and
`-40418 = TPAP_AUTHENTICATION_FAILED` exist in its enum (`common/CameraErrorCode.java:30-34`)
but were **not** observed: this camera answers `-40401` to an undecryptable body. `-40209`
is named `INVALID_ARGUMENTS` in `full15/com/tplink/iot/debug/camera/CameraDebugErrorCode.java:23`.

### 5.4 Retry policy that works ✅ (`TapoV4.multiple()`)

```
with lock:
  for attempt in (0, 1):
      try:
          if no session or it expires within 60 s: login()   # INSIDE the try: a Wi-Fi blip during login gets the same single retry
          resp = ds(inner); break
      except TapoV4Error as e:      # plaintext refusal, login error, short reply, or CCM tag failure on the reply
          drop session                       # a refused /ds kills it camera-side anyway
          if attempt == 1 or e.code not in (-40401, -40421): raise
      except network error (requests.RequestException):
          drop session
          if attempt == 1: raise
then: top-level error_code not in (0, None) -> raise; per-sub-request error_code is checked by request()
```
i.e. **exactly one transparent re-login**, never a loop (login lockouts exist, §4.8). A login
`TapoV4Error` (lockout code, `pake_share` failure, `dev_confirm` mismatch → code `0`) and a
short / unauthenticated reply (code `None`) are raised at once, never retried. Callers add
caching on top (the camera dislikes polling): the web app caches status 30 s, the day list
120 s and a day's clips 20 s (`app/sd.py:162,188,218`). The live probe scripts additionally
paused ~0.7 s between successive `/ds` calls.

### 5.5 HTTP headers

✅ What the reference sends on `/ds` (sufficient):
```
Content-Type: application/octet-stream
Accept: application/octet-stream
Referer: https://<ip>:443:443        ← sic: tapo_v4.py builds f"{base}:{port}" where base already
                                       contains the port. Harmless: the camera does not check it.
User-Agent: Tapo CameraClient Android
requestByApp: true
(+ python-requests defaults: Host, Accept-Encoding, Connection: keep-alive, Content-Length)
```

📖 The app's exact OkHttp 4.11.0 header set, in wire order (`com/tplink/libtapotpap/TpapAccessApi.java:7-13`,
interceptor `nu0/b.java:19-22`, client factory `lu0/yj.java:65-106`):

```
POST /stok=<stok>/ds HTTP/1.1          POST / HTTP/1.1                (login)
Connection: keep-alive                  Referer: https://<ip>:443
Accept: application/octet-stream        Accept-Encoding: gzip, deflate
Referer: https://<ip>:443               User-Agent: Tapo CameraClient Android
Accept-Encoding: gzip, deflate          Connection: Keep-Alive
User-Agent: Tapo CameraClient Android   requestByApp: true
Connection: Keep-Alive                  Accept: application/json
requestByApp: true                      Content-Type: application/json      (no charset)
Content-Type: application/octet-stream  Content-Length: <len>
Content-Length: <len>                   Host: <ip>                          (no :443)
Host: <ip>
```
- `Connection` really is sent twice on `/ds` (static `keep-alive` + interceptor `Keep-Alive`).
- `Accept: application/json` is added only when no `Accept` is already set.
- **Not sent**: `Cookie`, `Authorization`, `seq`, `tapo_tag` (those two belong to the V3
  `LocalSecureAccessApi.java:6-10`), any query string (the interceptor's query provider is
  `null` for local cameras, `nu0/b.java:24-61`, `x0.java:203-205`).
- TLS: trust-all manager **unless `tpap.tls == 2` and a root-CA string is supplied** (then that
  CA is pinned, `transport/local/d2.java:60-72`); hostname verifier always true; no client cert;
  ALPN offers `h2, http/1.1` (if a device ever negotiated h2, OkHttp would drop
  `Connection`/`Host`; ✅ HTTP/1.1 is what works here); 30 s connect/read/write timeouts
  (`lu0/yj.java:15-50`).
- **stok in the path**: Retrofit `@Path` (not pre-encoded) percent-encodes only
  space `" < > ^ `` ` `` { } | \ ? #`, `/`, `%` and non-ASCII; `! * ( ) ~ ' = + , ; : @ & $`
  stay raw (`full9/retrofit2/z.java:80-95`). ✅ A fully percent-encoded stok is rejected with
  `-40421` (`TESTS.md` B2). If a stok ever contains `% / ? #`, encode just those.

### 5.6 Inner JSON rules

- ✅ Compact UTF-8 JSON, only `method` and `params` at each level - no `id`,
  `requestTimeMils`, `terminalUUID`. 📖 `model/Request.java`, Gson without nulls (`z2.java:18-22,78-81`).
- Sub-request `params` have the shape `{module:{section:data}}` (or `{module:data}` when the
  section is the literal `"null"`), e.g. `{"harddisk_manage":{"table":["hd_info"]}}`.
  📖 `model/TypeAdapter__TypeAdaptersKt.java:199-231`, `Module.java`, `Section.java`.
- ✅ Several sub-requests per call work (3 in one call verified: `getTimezone`,
  `getClockStatus`, `getAppComponentList`).
- 📖 Only ~5 onboarding methods are sent **bare** by the app: `getConnectStatus`,
  `setLanguage`, `setCloudServerType`, `scanApList`, `stopRoiClarityPeek`
  (`lu0/uj.java:1542,2239,2340,2432,2975,3820,4607`). Untested.
- 📖 "Anonymous" requests are **not** encrypted even on a TPAP camera: plaintext JSON to
  `POST /` via `LocalAccessApi.multipleAnonymous / singleAnonymous` (`b2.java`, `x0.java:1136-1139,1198-1201`). Untested.
- 🌐 Other public camera clients also know the top-level forms
  `{"method":"get","device_info":{"name":["basic_info"]}}` / `set` / `do`. Untested here.

### 5.7 Where the 24-byte "TSLP" frame is really used 📖

The frame of `dm1/a.java` belongs to the app's **netty TCP / BLE** TPAP transport
(`com/tplink/tls/session/d.java:23-40,78`, `TslpBusinessRequest.java:16-17`, instantiated only
by BLE transports `mu0/k.java:226`, `f11/l.java:46`, `m01/k.java:61`, `TPBLETpapClient.java:396`).
That transport also uses `incrementAndGet` (first seq = `start_seq + 1`). **Never send it to
`/ds`.** Layout, for the record (`dm1/a.java:16-98`):

| Offset | Size | Content |
|---|---|---|
| 0 | 1 | `0x01` (constant) |
| 1 | 1 | `0x02` if the "reply" flag is set, else `0x01` |
| 2 | 1 | `0x01` (no channel string) or `0x02` (business request with channel) |
| 3 | 1 | `0x00` |
| 4 | 4 | payload length, big-endian |
| 8 | 8 | channel string UTF-8, truncated / zero-padded to 8 bytes |
| 16 | 4 | sequence, big-endian int32 |
| 20 | 4 | CRC32 (zlib) of the **whole frame** computed with the placeholder `0x92BF30ED` (int `-1832963859`) in this field |
| 24 | … | payload (`ct ‖ tag`) |

### 5.8 Cross-check: the same transport in TP-Link IoT devices 📖

Every `hm1.a0` user (camera, IoT plugs/bulbs, robot, Kasa) shares §5.1-5.2 byte for byte.
Differences on the IoT side, recorded so nobody mixes them up:
- inner JSON = `{"method","params","requestTimeMils":<long>,"terminalUUID":…}`, no
  `multipleRequest` requirement (`IoTTpapTransport.java:826-830`, `TPIoTRequest.java:6-10`);
- username always `md5hex("admin")`; credential for pake 2/5 = `"<account e-mail>/<raw password>"`
  (`IoTTpapTransport.java:483-535`);
- a real in-memory cookie jar, `Accept: application/json` added by its interceptor;
- IoT only: error bodies `-2402`, `-40421`, `-40420` drop the cached session; ≥ 5
  `failed_attempts` ⇒ 30 s login throttle (`transport/tpap/f.java:66-98`,
  `IoTTpapTransport.java:330-344,799-810`).

**Not** an IoT difference - shared by every `hm1.a0` user, the camera path included
(`j2.java:122-124` builds `new hm1.a0(…)`): one automatic re-login + retry when the failure is a
`TlaException` with code `-2004`, `-2001`, `-2402` or `-2101` (`hm1/a0.java:111-120,342-350`,
log text "Triggering login and retry"; see also §10.1).

🌐 Public implementations of the identical `/ds` layout: python-kasa PR #1592
(`kasa/transports/tpaptransport.py`: `struct.pack(">I", seq) + AESCCM(key, tag_length=16).encrypt(nonce, pt, None)`)
and TA2k/ioBroker.tapo (`tpapCipher.ts`). Neither documents a camera test; this camera is, to
our knowledge, the first confirmed one.

---

## 6. Control methods catalogue (all over `/ds`, each one entry of `requests`)

All requests below are shown as the **sub-request**; wrap them per §5.1. Responses are the
real decrypted `result` of that sub-request.

### 6.1 Verified live ✅

**getDeviceInfo**
```json
{"method":"getDeviceInfo","params":{"device_info":{"name":["basic_info"]}}}
```
```json
{"device_info":{"basic_info":{"device_type":"SMART.IPCAMERA","device_info":"C510W 2.0 IPC",
 "features":3,"barcode":"","device_model":"C510W","sw_version":"1.3.4 Build 260523 Rel.33481n",
 "device_name":"C510W 2.0","hw_version":"2.0","device_alias":"Tapo_C510W_XXXX","mobile_access":"0",
 "mac":"AA-BB-CC-DD-EE-FF","dev_id":"<40 hex>","hw_id":"<32 hex>","oem_id":"<32 hex>",
 "hw_desc":"00000000000000000000000000000000","manufacturer_name":"TP-Link","region":"EU", …}}}
```
(The whole reply was 761 bytes on the wire; the tail after `region` was not recorded.)

**getSdCardStatus**
```json
{"method":"getSdCardStatus","params":{"harddisk_manage":{"table":["hd_info"]}}}
```
```json
{"harddisk_manage":{"hd_info":[{"hd_info_1":{
 "disk_name":"1","rw_attr":"rw","status":"normal","detect_status":"normal","write_protect":"0",
 "percent":"0","type":"local","record_duration":"0","record_free_duration":"0",
 "record_start_time":"1779527888","loop_record_status":"1",
 "total_space":"111.3GB","total_space_accurate":"119453777920B",
 "free_space":"119.1MB","free_space_accurate":"124926940B",
 "video_total_space":"111.3GB","video_total_space_accurate":"119453777920B",
 "video_free_space":"119.1MB","video_free_space_accurate":"124926940B",
 "picture_total_space":"0B","picture_total_space_accurate":"0B",
 "picture_free_space":"0B","picture_free_space_accurate":"0B",
 "crossline_total_space":"0B","crossline_total_space_accurate":"0B",
 "crossline_free_space":"0B","crossline_free_space_accurate":"0B",
 "msg_push_total_space":"0B","msg_push_total_space_accurate":"0B",
 "msg_push_free_space":"0B","msg_push_free_space_accurate":"0B"}}]}}
```
All values are **strings**; `*_accurate` = bytes with a trailing `B`; `record_start_time` =
epoch seconds of the oldest recording; `loop_record_status:"1"` = loop recording on (so
"free" is always small). 📖 The app batches it with `GET_HARD_DISK_STATUS` and
`GET_CIRCULAR_RECORDING_CONFIG` (`u3.java:212`); ✅ alone works.

**getUserID** - only needed by the legacy listing
```json
{"method":"getUserID","params":{"system":{"get_user_id":"null"}}}      →  {"user_id":1}
```

**getClockStatus / getTimezone**
```json
{"method":"getClockStatus","params":{"system":{"name":"clock_status"}}}
  → {"system":{"clock_status":{"seconds_from_1970":1789758002,"local_time":"2026-09-18 21:00:02"}}}
{"method":"getTimezone","params":{"system":{"name":["basic"]}}}
  → {"system":{"basic":{"timing_mode":"ntp","zone_id":"Europe/Brussels","timezone":"UTC+01:00"}}}
```
Note the argument types: a **string** for `clock_status`, a **list** for `basic`. `timezone` is
the zone's *standard* offset; `local_time` does include DST (the pair above is UTC+02:00).
**Use `zone_id`** to compute day boundaries.

**getAppComponentList**
```json
{"method":"getAppComponentList","params":{"app_component":{"name":"app_component_list"}}}
  → {"app_component":{"app_component_list":[{"name":"sdCard","version":1}, …]}}
```
Full list on this camera (46): `sdCard:1, timezone:1, system:3, led:1, playback:6, detection:3,
alert:2, firmware:2, account:2, quickSetup:3, ptz:1, video:3, lensMask:2, lightFrequency:1,
dayNightMode:1, osd:2, record:1, videoRotation:1, audio:3, nightVisionMode:3, diagnose:1,
msgPush:3, deviceShare:1, tamperDetection:1, patrol:1, tapoCare:1, targetTrack:1, blockZone:1,
personDetection:2, needSubscriptionServiceList:1, whiteLamp:1, nvmp:1, detectionRegion:2,
recordDownload:2, recordDownloadOccupy:1, upnpc:2, iotCloud:1, staticIp:2, timeFormat:1,
hubManage:1, relayPreConnection:1, relayQuic:1, relayCdn:1, streamCapability:1, localCtrl:1, facTest:1`.
📖 What the relevant ones gate in the app (`model/CameraComponent.java:966-971,1032-1046,1114-1119,1172-1177`):
`playback >= 2` ⇒ use `searchVideoWithUTC`; `>= 3` ⇒ `searchDetectionList`; `>= 6` ⇒ send
`player_id`, `client_id` forced to 1, no `getUserID`; `recordDownload >= 1` ⇒ download UI,
`>= 2` ⇒ download also over relay/P2P; `recordDownloadOccupy` ⇒ only an app-side flag to keep
several download connections open - **no "occupy" request exists** (`s21/c.java:340-345`, `ma1/s1.java:2980-2996`).

**searchDateWithVideo** - days that have video
```json
{"method":"searchDateWithVideo","params":{"playback":{"search_year_utility":
   {"channel":[0],"start_date":"20260701","end_date":"20260918"}}}}
  → {"playback":{"search_results":[{"search_results_1":{"date":"20260701"}},
                                   {"search_results_2":{"date":"20260702"}}, …]}}
```
Dates are `YYYYMMDD` (camera-local days). A 2-year window (today−730 … today+1) in one call works.

**searchVideoWithUTC** - what the app uses on this firmware; **the listing to use**
```json
{"method":"searchVideoWithUTC","params":{"playback":{"search_video_with_utc":
   {"channel":0,"start_time":1789682400,"end_time":1789768799,
    "start_index":0,"end_index":99,"player_id":"<32 hex>"}}}}
  → {"playback":{"search_video_results":[
        {"search_video_results_1":{"startTime":1789683060,"endTime":1789683144,"video_type":"2"}}, …
        {"search_video_results_69":{"startTime":1789757423,"endTime":1789757489,"video_type":"2"}}],
      "to_be_continued":0}}
```
- `start_time`/`end_time` are **integers** (UTC epoch s); `video_type` is a **string**.
- `player_id`: any stable 32-hex string works (the reference uses `uuid4().hex.upper()`, one
  per process). 📖 The app sends a persistent 32-char upper-hex "term UUID" (`libtapoiotnetwork/utils/m.java`).
- With `"id":<user_id>` instead of `player_id` → **`-71103`** on this playback-v6 camera.
- Paging: ✅ live only `to_be_continued: 0` was seen (69 clips < 100, one page). 📖 + reference
  (`TapoV4.search_videos_utc`, tested offline only, `tests/test_tapo_v4_ds.py`
  `test_listing_helpers_unwrap_and_paginate`): `to_be_continued == 1` ⇒ ask the next page,
  `start_index += 100` (`100..199`, …); stop when it is `0`/absent or a page comes back empty
  (`PlayBackBaseRepository.java:1654-1668,2191-2198`). Live paging by `start_index`/`end_index`
  was verified only with `searchVideoOfDay` (below).

**searchVideoOfDay** - legacy, also works
```json
{"method":"searchVideoOfDay","params":{"playback":{"search_video_utility":
   {"channel":0,"date":"20260918","start_index":0,"end_index":99,"id":1}}}}
  → {"playback":{"search_video_results":[
        {"search_video_results_1":{"startTime":1789683060,"endTime":1789683144,"vedio_type":2}}, …],
      "filter_enable":false}}
```
- `id` = the `getUserID` value; `date` = camera-local day; `vedio_type` (sic) is an **int**;
  no `to_be_continued` key here → the reference pages until a page comes back shorter than 100.
- ✅ Paging by `start_index`/`end_index` works. 69 clips were returned for 2026-09-18, identical to the UTC listing.

Common to both listings: `startTime`/`endTime` are true **UTC epoch seconds**; list items are
wrapped in single-key maps `search_video_results_N` (take the map values; N is 1-based and
continues across pages); consecutive clips can be back-to-back (`endTime` of one = `startTime`
of the next).

### 6.2 Listing rules from the app 📖

- Day bounds = midnight … next midnight − 1 computed **in the camera's `zone_id`**
  (`cu0/t.java` k(), `PlayBackBaseRepository.java:1244-1250`). For Europe/Brussels
  2026-09-18: `1789682400 … 1789768799`.
- Pages of 100 (`start_index = a`, `end_index = a + 99`, `a += 100`), stop when
  `to_be_continued == 0`, or, if the key is absent, when `a` exceeds the items received;
  hard cap index `12288` (`PlayBackBaseRepository.java:1654-1668,2191-2198,2498`).
- `searchVideoOfDay` is used by the app only for `playback` v1 devices; for that legacy
  method it has DST work-arounds that also fetch the adjacent day and merge
  (`PlayBackBaseRepository.java:2495-2529`) - inference: the firmware buckets days without
  DST. Prefer `searchVideoWithUTC`.
- Optional extra keys in listing requests: `child_device_id`, `mac` (hub children).
- Optional response siblings: `filter_enable` (camera can filter playback by event type),
  `filter_chn_enable`, `playback_delete_v2_enable`; optional per-item `event_info`, `chn_times`
  (`model/DailyPlaybackList.java:7-20`, `DailyPlaybackItem.java:8-21`). A missing type defaults to `"2"`.
- 🌐 pytapo: on `-71103` / `-71105` refresh the user id and retry; HomeAssistant insists a
  `searchVideoOfDay` for the date must precede an 8800 **playback** or the camera sends no
  data. ✅ Not needed for the `download` request as used here: the web app lists with
  `searchVideoWithUTC` and downloads work without any prior `searchVideoOfDay` (it calls the
  legacy method - after `getUserID` - only as a fallback when the UTC listing is empty or the
  method is refused, `app/sd.py` `_list_day()`).

### 6.3 `video_type` / `vedio_type` = the app's `PlayBackEventType` 📖

(`business/model/PlayBackEventType.java:6-34`; UI copy `full17/…/playback/PlayBackEventType.java:11-42`.)
✅ Only `2` has been seen on this camera so far.

| Code | Name | Code | Name | Code | Name |
|---|---|---|---|---|---|
| 1 | TIMING (continuous / scheduled) | 12 | ALARMMEOW | 23 | BABYLEAVE |
| 2 | MOTION | 13 | ALARMGLASS | 24 | BABYCAREGIVER |
| 3 | TAMPER | 14 | ALARMSMOKE | 25 | BABYASLEEP |
| 4 | LINECROSS | 15 | DELIVERPACKAGE | 26 | BABYAWAKEUP |
| 5 | AREAINTRUSION | 16 | PICKUPPACKAGE | 27 | FACECOVER |
| 6 | HUMAN (person) | 17 | DOLLBELLRINGMISSED | 28 | SAFEFANCEOUT |
| 7 | BABYCRY | 18 | DOLLBELLRINGANSWERED | 30 | BABYMOTION |
| 8 | VEHICLE | 19 | ANTITHEFT | 31 | PANORAMICVIDEO |
| 9 | PET | 20 | FACEDETECTION (UI enum only) | 33 | ANIMAL |
| 10 | RINGALARM | 21 | UNFAMILIARFACEDETECTION (UI only) | 36 | CO_ALARM |
| 11 | ALARMBARK | 22 | UNFAMILIARPERSONDETECTION (UI only) | | |

A coarser enum `PlayBackVideoType` also exists: `1` TIMING, `2` DETECTION, `3` AOV.
The stream-side `event_type:[1,2]` filter is literally `[TIMING, MOTION]`.

### 6.4 App-only methods 📖 (module `playback` unless stated; none tested live)

| Method | Params (`{"playback":{<section>:…}}`) | Result |
|---|---|---|
| `searchDetectionList` (per-event list, `playback >= 3`) | `search_detection_list: {start_time, end_time, channel:0, start_index, end_index[, child_device_id, mac]}` (ints, same day bounds and paging) | `playback.search_detection_list`: **flat list** (not map-wrapped) of `{start_time, end_time, alarm_type, events_1, file_id, event_info[{face_id, face_bitmap, name, tag}], chn_events{…}, modify_event_type}` + `snapshot_enable` (bool) + `to_be_continued` |
| `searchCurrentDetectionListWithUTC` | `search_current_detection_list_with_utc` | same item type |
| `searchCurrentVideoWithUTC` | `search_current_video_with_utc: {id, channel, start_time, end_time, player_id, total_num (default 1), index_order}` | clips around "now" |
| `checkDetectEventState` | `check_detect_event_state: {timestamp}` | event state at that time |
| `getLastAlarmInfo` | `{"system":{"name":["last_alarm_info"]}}` | batched by the app with `getDeviceInfo` |
| `setLocalCtrl` | `{"local_ctrl":{"set_local_ctrl":{pake_password, pake_verify{iterations, salt, verify_w0, verify_w1, verify_L}}}}` | **writes the camera's PAKE verifier - do not call** (`pu0/i1.java:87-123`, `lu0/dk.java:1783`) |
| `getScaleList` 🌐 | (method name only, from Depau's firmware map) | playback scales supported |

- `alarm_type` uses the §6.3 numbering (🌐 ioBroker.tapo confirms `6` = person).
- `events_1` is a 64-bit mask: **bit *i* set ⇒ event type *i*+1** (e.g. `34` = bits 1 and 5 =
  MOTION + HUMAN) (`src6/com/tplink/libtpmediaother/database/model/SnapshotBean.java` parseTypeList).
- `file_id` falls back to `String(start_time)`; it is what the app passes as `start_time` of a
  snapshot request (§7.6.2).
- Citations: method strings `model/Method.java:52-60,295`; sections `model/Section.java`;
  builders `lu0/dk.java:746-748,814-816,1347-1349,1397-1407,1424-1426,1462-1464,1478-1480,1544-1552`;
  models `SnapshotPlaybackFilter.java:7-25`, `SnapshotPlaybackItem.java:9-32`, `DetectionList.java:8-15`,
  `CurrentDailyPlaybackUtc.java:6-22`, `DetectEventRequestParam.java:7-8`.
- There is **no** `/ds` method that returns image bytes; thumbnails come from the media port (§7.6.2).

---

## 7. Media port 8800 - thumbnails, clip download, playback

Wire format first documented by pytapo 🌐; the `download` request, ack cadence, stop message
and everything tagged 📖 come from the official app (connection classes `zb1/b.java` =
"Video Download" connection, `bd1/e.java` = VOD/playback connection, `oa1/a.java` = base
stream client, `l61/b.java` = image download).

### 7.1 Transport

✅ Plain TCP to `<ip>:8800`, an HTTP-like exchange that never ends: the client sends one
`POST /stream` head and then **multipart parts** for the life of the socket; the camera
answers one response head and then multipart parts. `TCP_NODELAY` is set by the reference.

### 7.2 Authentication (HTTP Digest) and key exchange

✅ **Step 1** - unauthenticated head:
```
POST /stream HTTP/1.1\r\n
Content-Type: multipart/mixed;boundary=--client-stream-boundary--\r\n
Connection: keep-alive\r\n
Content-Length: -1\r\n
\r\n
```
✅ Real reply:
```
HTTP/1.0 401 Unauthorized
Server: Streamd
Date: Fri, 18 Sep 2026 19:00:34 UTC
Pragma: no-cache
Cache-Control: no-cache
Content-Length: 0
WWW-Authenticate: Digest realm="TP-Link IP-Camera",algorithm="MD5",encrypt_type="3",qop="auth",nonce="09939140a84cc97b2a27579bb823b2e1",opaque="64943214654649846565646421"
X-Preconn: 1
X-Hb: 5
Connection: close
```
`Connection: close` ⇒ **open a new TCP connection** for step 2 (the nonce stays valid).

✅ **Step 2** - same head plus `Authorization`:
```
hashed_pwd = SHA256(cloud_password).hexdigest().upper()      # because encrypt_type="3"
                                                             # (MD5(...).hexdigest().upper() when encrypt_type is absent / older firmware 🌐)
HA1      = md5_hex( "admin" ":" realm ":" hashed_pwd )
HA2      = md5_hex( "POST:/stream" )
response = md5_hex( HA1 ":" nonce ":" "00000001" ":" cnonce ":" "auth" ":" HA2 )

Authorization: Digest username="admin",realm="TP-Link IP-Camera",uri="/stream",algorithm=MD5,nonce="<nonce>",nc=00000001,cnonce="<cnonce>",qop=auth,response="<response>",opaque="<opaque>"
```
`cnonce` = any client string (reference: 24 random hex chars). All `md5_hex` are lowercase.

✅ Reply `200` with a `Content-Type: multipart/mixed;boundary=--device-stream-boundary--`
(take the device boundary from there, default `--device-stream-boundary--`) and a
**`Key-Exchange`** header: space-separated `key="value"` items, of which `nonce` and `username`
are used. 🌐 Shape captured on a C200 (Depau 2020):
```
HTTP/1.0 200 OK
Server: Streamd
Content-Type: multipart/mixed;boundary=--device-stream-boundary--
Key-Exchange: cipher="AES_128_CBC" username="admin" padding="PKCS7_16" algorithm="MD5" nonce="<nonce>"
Connection: keep-alive
```
A second `401` is what a wrong cloud password is *expected* to produce: the reference raises
`MediaError` on it (`MediaSession.open()`) and the app maps it to `-3 DIGEST_AUTHORIZE_FAIL` 📖
(§10.2) - **not triggered live** (no wrong-password test was run against the media port).

### 7.3 Payload encryption

✅ Parts with header `X-If-Encrypt: 1` are **AES-128-CBC, PKCS#7**, with
```
key = MD5( kx_nonce ":" hashed_pwd )      # raw 16 bytes; hashed_pwd = the upper-hex string of §7.2
iv  = MD5( kx_username ":" kx_nonce )     # raw 16 bytes; kx_username = "admin"
```
and the cipher is **re-initialised from that same IV for every part**. JSON control parts
from the camera come with `X-If-Encrypt: 0` (plaintext). The client's JSON parts are sent in
plaintext. The reference reports a PKCS#7 padding error as a probable wrong cloud password
(`MediaSession.parts()`; app: `-2001 STREAM_DATA_DECRYPT_ERROR` 📖) - not triggered live.
📖 The app also knows an HKDF cipher variant with per-part `X-Nonce` / `X-Data-Hmac` headers
(`y31/c.java:139-175`); not seen on this camera.

### 7.4 Multipart framing, both directions

✅ **Client → camera**, every part:
```
----client-stream-boundary--\r\n          ("--" + boundary)
<Header: value\r\n>*
Content-Length: <body bytes>\r\n
\r\n
<body>\r\n
```
✅ **Camera → client**: each part is the delimiter line `----device-stream-boundary--\r\n`
(`"--"` + the boundary given in the 200's `Content-Type`, like the client side; 🌐 Depau's capture
shows exactly that line, 📖 the app matches any line *containing* `--device-stream-boundary--`,
`src6/oa1/a.java:319-327`), header lines, an empty line, then exactly `Content-Length` body bytes.
The reference does not parse lines: it searches the byte stream for the boundary value
(`_read_until(boundary)`), reads headers up to `\r\n\r\n`, reads `Content-Length` bytes, and lets
the next boundary search skip whatever separates two parts - do not rely on a fixed trailer
after the body. Header names are case-insensitive. Headers seen:

| Header | On | Meaning |
|---|---|---|
| `Content-Type` | all | `application/json`, `video/mp2t`, `image/jpeg` |
| `Content-Length` | all | body size (ciphertext size when encrypted) |
| `X-If-Encrypt` | all | `1` = AES-CBC body, `0` = plaintext |
| `X-Session-Id` | data parts, some notifications | the session the part belongs to |
| `X-Data-Sequence` | `video/mp2t` | per-session counter, **starts at 0**, +1 per data part |
| `X-Data-PTS` | `video/mp2t` | **wall clock of that access unit in ms** (UTC epoch × 1000, e.g. `1789688911000` for a clip whose `startTime` is `1789688911`) |
| `X-If-IFrame` | `video/mp2t` | `1` on key frames |

Real first data part of a download:
`{content-type: video/mp2t, content-length: 64864, x-session-id: 21, x-if-encrypt: 1, x-data-sequence: 0, x-data-pts: 1789688911000, x-if-iframe: 1}`.
📖 The app additionally reads `X-Stream-Type` and `X-Data-PTS-Ext` (`src6/zb1/b.java:774-786`);
they were **not present** on the parts observed here.

The camera's JSON is *not* compact (note the spaces) - parse it, do not string-match:
```
{"type":"response", "seq":1, "params":{"error_code":0, "session_id":"21"}}                      (74 bytes)
{"type":"notification", "params":{"event_type":"stream_status", "status":"finished"}}          (85 bytes)
```

### 7.5 Requests and flow control

✅ A request is one JSON part:
```
headers: X-Data-Window-Size: 50          # reference: on EVERY request part, `stop` included
         Content-Type: application/json
         [X-Session-Id: <id>]            # reference: ONLY on do-requests (`stop`). Follow-up `get` requests on the
                                         # same connection (snapshots in a row, §7.6.2) go WITHOUT it ✅, seq = 2, 3, ...
         Content-Length: <n>
body:    {"type":"request","seq":<n>,"params":{ <key>: {...}, "method":"get"|"do" }}
```
(Reference: `MediaSession.request(params, with_session=False)`; only `stop()` passes
`with_session=True`.) 📖 The app behaves differently: it adds `X-Session-Id` to every part it
sends once it holds a session id, including a follow-up `get download`
(`src6/bd1/e.java:143-151`, `src6/zb1/b.java:112-127`); its download connection puts
`X-Data-Window-Size: 50` only on parts whose JSON contains `download` (`src6/zb1/b.java:118-120`),
i.e. not on `stop`.

`seq` = client counter starting at 1 (any int; 🌐 pytapo uses a random one). The camera's
`response` echoes it. `session_id` (a **string**) comes back in the first response and in
`X-Session-Id` of the data parts.

✅ **Acks**: the camera sends at most *window* un-acknowledged data parts. With
`X-Data-Window-Size: 50`, acknowledge **every 25th** data part (`X-Data-Sequence % 25 == 0`;
the reference skips sequence 0 ✅; the app's `l0 % 25 == 0` test also acks sequence 0 📖,
`src6/zb1/b.java:783-784`) with:
```
headers: X-Data-Received: <that sequence number>
         X-Session-Id: <session_id>
         Content-Type: application/json
         Content-Length: 65
body:    {"type":"notification","params":{"event_type":"stream_sequence"}}
```
Without acks the camera stalls once the window is full. 📖 Window `"50"` and `% 25` are
hard-coded in the app for download, playback and image connections (`src6/zb1/b.java:85-93,119,746,783-784`,
`src6/bd1/e.java:57,973-981`, `src5/l61/b.java:585`). 🌐 pytapo acks once per *full* window
(stop-and-wait) with windows 50/200/500.

### 7.6 Request catalogue

#### 7.6.1 `download` video - **the request to use** ✅

```json
{"type":"request","seq":1,"params":{"download":{"client_id":1,"channels":[0],"media_type":0,
  "start_time":"<startTime>","end_time":"<endTime>","player_id":"<32 hex>"},"method":"get"}}
```
- `start_time` / `end_time`: epoch seconds **as strings** - use a clip's exact
  `startTime`/`endTime` from §6.
- ✅ Delivered as fast as the link allows: a **66 s clip in 6.9 s** over Wi-Fi (~10× realtime),
  **every frame + audio** (990/990 frames counted live; 🧪 the capture of the
  1713-part / 10 045 028-byte run, analysed offline, holds 989 video frames + 659 audio PES, see §8.1).
- ✅ The camera **stops at `end_time`** and sends
  `{"type":"notification","params":{"event_type":"stream_status","status":"finished"}}`.
- ✅ First reply: `{"type":"response","seq":1,"params":{"error_code":0,"session_id":"21"}}`.
- 🧪 In download mode the end is signalled **only** by that JSON notification (no in-band
  `0x12` tag was present in the captured stream, §8.4).

📖 Full `GetDownloadParams` field list (all optional, nulls omitted;
`com/tplink/libtpcommonstream/stream/control/request/param/GetDownloadParams.java:7-53`,
builder `z31/a.java:231-263`):

| Key | Type | App usage |
|---|---|---|
| `client_id` | int | `1` on playback-v6 cameras ("no need userId"), else the `getUserID` value (`PlayBackRepository.java:485-501`) |
| `channels` | [int] | `[0]` (or the channel id) |
| `media_type` | int | `0` VIDEO, `1` PUSH_IMAGE, `2` NORMAL_IMAGE, `3` THUMBNAIL, `5` NICE_MOMENTS_IMAGE (`src5/…/control/common/DownloadMediaType.java:10-14`); video download hard-codes 0 (`xb1/j0.java:16-17`) |
| `start_time`, `end_time` | string | epoch seconds; both always set for video |
| `player_id` | string | app UUID, only for playback-v6 / sub-devices (`ma1/s1.java:1340-1363`) |
| `event_type` | [int] | only when the timeline event filter is active; default `[1,2]` |
| `download_type` | string | `"normal"` \| `"trajectory"` \| `"timelapse"`; omitted for ordinary clips (`src6/…/VideoDownloadType.java:6-8`) |
| `audio_config` | object | `{"encode_type":"G711alaw"\|"G711ulaw"\|"AAC_ADTS"\|"OPUS"\|"G722","sample_rate":"8"\|"16"}` (kHz as string) when the mic config is known |
| `last_pts` | string | resume point; `null` for the normal fetcher - on retry the app instead moves `start_time` to `lastReceivedPts/1000` (`xb1/g0.java:55-57` `a()` = `j/1000` - the same code is at `src6/xb1/g0.java:74-76` - and `xb1/g0.java:97-99` `e()` returns `null`; `wb1/a.java:176-188`) |
| `streams` | [int] | optional stream ids |
| `file_id`, `range`, `splmom_snap_id`, `dev_id`, `mac` | | file-based / nice-moment / hub-children variants; `range` also appears in the response |

App-style example 📖 (field set as the app builds it for a playback-v6 camera with a known mic
config; the key ORDER shown is a guess - Gson's reflection order could not be pinned down from
the R8 output - and is irrelevant: the camera accepts the reference's `type, seq, params` order ✅):
```json
{"params":{"download":{"audio_config":{"encode_type":"G711alaw","sample_rate":"8"},"client_id":1,"end_time":"<END>","media_type":0,"player_id":"<UUID>","start_time":"<START>","channels":[0]},"method":"get"},"seq":<N>,"type":"request"}
```
There is **no** `scale`/`speed` field in download. 📖 Response class `GetDownloadResponse
{error_code, session_id, range, image_list, seq_image_lens}`. If `finished` arrives before any
video PTS the app raises `-10002 INVALID_DATA`. The app's queue holds ≤ 10 items, one clip at
a time per device, a task is dropped after 1 failed retry (`wb1/a.java:85-87,163-171`).

#### 7.6.2 `download` snapshot - per-recording thumbnail ✅

```json
{"type":"request","seq":1,"params":{"download":{"client_id":1,"channels":[0],"media_type":2,
  "start_time":"<startTime>","player_id":"<32 hex>"},"method":"get"}}
```
- ✅ Reply sequence: `response` (session id) → **one `image/jpeg` part** (encrypted, 640×360,
  ~40 KB, `X-Session-Id`) → `stream_status: finished`. The JPEG is a frame **of that recording**
  (its OSD time matches). Only single-part images (~40 KB) were seen live. 📖 The app does not
  assume one part: it **concatenates every image part of the session until `finished`** (buffer
  512 000 bytes per `X-Session-Id`, `src5/l61/b.java:610-644,693-694` j0()); since a part never exceeds 64 860 plaintext bytes (§8.1)
  a bigger image would come in several `image/jpeg` parts. The reference `fetch_snapshot()` keeps
  only the **last** image part (`image = data`) - concatenate if you ever request larger images.
- ✅ Several snapshots **in a row on one connection** work: send the next request after
  `finished` (~0.3 s each; opening a session costs ~1.5 s; 6 snapshots in 3.7 s).
- ✅ `media_type: 3` returns a **live** snapshot (OSD = now), not the recording's.
- ✅ **A connection is bound to the media type of its first request**: a video request sent on a
  connection that served a snapshot gets `response` `seq:2` with the **same** `session_id` and
  the snapshot JPEG again. Use separate connections for thumbnails and video.
- 📖 The app uses `media_type 2` with `start_time` = the detection item's `file_id` (or its
  `start_time`), window 50 (`src5/z31/a.java:154-182`, `src5/i61/d.java`, `src5/l61/b.java` j0()).
  The camera may also answer `image/avc` or `image/hevc` (one encoded key frame that the app
  decodes and re-encodes to JPEG; `src5/h61/b.java:31-33`) - not seen here. `StreamStatus` also
  has `total_len`, `image_id`, and a status `"image_ended"`.
- 📖 A second image API exists, `{"image":{"type":"playback_display","start_time":…,"channel":…,
  "mac":…,"seq_image_type":…,"seq_image_list":[…]},"method":"get"}` (`a41/k0.java:697-707,775-783`,
  `GetCoverParams.java:11-26`); it is only wired for face-detection devices/hubs - unlikely on a C510W.

#### 7.6.3 `playback` - the *player* path ✅ (works, but not suited to fetching clips)

Tested live in pytapo's form:
```json
{"type":"request","seq":1,"params":{"playback":{"client_id":1,"channels":[0,1],"scale":"1/1",
  "start_time":"<start>","end_time":"<end>","event_type":[1,2]},"method":"get"}}
```
- ✅ Paced at **exactly 1.0× realtime**.
- ✅ It does **not** stop at `end_time`: it rolls on into the following recordings
  (🧪 the captured TS shows the in-band UTC tag jumping to the next clip's `startTime`
  while the PTS stays continuous).
- ✅ `scale` `"4/1"` and `"16/1"` = **key frames only**, **no audio** (ffprobe `r_frame_rate`
  2 fps / 8 fps; no PID `0x45` packet at all in the captures). 🧪 In the captures the camera
  sends one key frame per 2 s GOP at `4/1` and one key frame per ~8 s of recording at `16/1`,
  **re-stamped ≈ 0.5 s apart in PTS** (the in-band UTC tags step by 2 s / 8 s - sometimes 6 s -
  while the PTS steps by 44 460…45 900 ticks). The 135-frame `4/1` capture (35 s to fetch) and
  the 142-frame `16/1` capture (47 s) each hold ~67 s of *stream PTS* but had already rolled
  through 4 recordings (UTC tags `1789688911 → 1789701221`, 3.4 h of timeline) and through 5.6 h
  of timeline (`… → 1789709239`) respectively: `scale` is a player fast-forward, **not** a
  faster way to fetch one clip, and it does not stop at `end_time` either.
- ✅ Parts carry `X-Data-PTS` too (wall-clock ms), interleaved audio from the first frames.

📖 Full `GetVodParams` field list (`…/request/param/GetVodParams.java:7-87`, builder `src5/z31/a.java:29-109`):
`audio_config, auto_seek, auto_switch_date, camera_mac, client_id, data_filter_tag, det_origin,
end_time, face_id, file_id, filter, ignore_limit, interval, media_type, play_channel, play_type,
player_id, range, scale, speed, start_time, traj_start_time, vod_type, channels, streams, event_type`.
The app sends `channels:[0]` (not `[0,1]`), `filter:true` whenever `event_type` is non-empty,
and **never sends `end_time`** for local playback (it passes `0L`, and the builder only writes
`end_time` when `> 0`: `src5/com/tplink/libtpmediamanager/i.java:132,180,220,421`, `src5/z31/a.java:76-78`)
- which explains why the firmware does not bound playback. App-style request:
```json
{"type":"request","seq":1,"params":{"playback":{"channels":[0],"client_id":1,"scale":"1/1",
  "start_time":"<epoch>","player_id":"<uuid>","vod_type":0,"auto_seek":0,"auto_switch_date":"0",
  "event_type":[1,2],"filter":true},"method":"get"}}
```
(`player_id, vod_type, auto_seek, auto_switch_date` only on playback-v6 devices.) Scale
strings (`src5/…/control/common/VodScale.java:10-18`): `"1/16","1/8","1/4","1/2","1/1","2/1","4/1","8/1","16/1"`.
Response: `{"error_code":0,"session_id":"<id>","speed":…}` (`GetPlaybackResponse.java:7-13`).

How to bound a playback if you must use it: §8.4 (UTC tags) - or an overrun guard on the
video PTS span (the reference stops at `(end − start) + 5 s`).

#### 7.6.4 do-requests 📖 (all with `X-Session-Id`; only `stop` is exercised live)

| Purpose | `params` | Notes |
|---|---|---|
| **stop / teardown** | `{"stop":"null","method":"do"}` | the **string** `"null"`; ✅ sent by the reference before closing. On the RTC (WebRTC) transport the value is `"playback"` (`src6/ja1/l0.java:124-128`) / `"download"` (`src6/ja1/i0.java:26`) instead |
| pause | `{"pause":"null","method":"do"}` | defined (`DoPauseRequest.java:9`); not used on local playback - the app pauses by **not reading the socket** (queue > 300 frames → stop reading, < 150 → resume: `src6/xd1/r0.java:1465-1479,1576-1587`) |
| resume | `{"play":"null","method":"do"}` | defined (`DoResumeRequest`) |
| seek / change scale | `{"play":{"scale":"4/1","auto_seek":"0","auto_switch_date":"0","start_time":"<epoch>"[,"end_time":"<epoch>"][,"streams":[…]][,"camera_mac":"…"]},"method":"do"}` | `auto_seek` (SeekMethod): `0` NORMAL, `1` SEEK_AFTER, `2` SEEK_BEFORE. Response params `{error_code, start_time, end_time, scale}`. Timeouts 10-15 s. An older seek re-sends a full `get playback` on the same connection (`src5/a41/k0.java:708-733,788-840`, `src6/ma1/s1.java:2140-2175,4007-4048,4450-4487`) |
| finish | `{"finish":"null","method":"do"}` | RTC path only |
| cancel a download but keep the connection | *notification* `{"type":"notification","params":{"event_type":"stream_status","status":"stopped"}}` (82 bytes) with `X-Session-Id` | then the same connection/session is reused for the next `get download` (`src6/zb1/b.java:112-136,731-739`) |
| others (names only) | `change_audio`, `change_resolutions`, `change_streams`, `change_life_time`, `playback_add_channels:[int]`, `preview_add_channels:{channels,streams,resolutions}`, `remove_channels:[int]` | `…/stream/control/request/*.java`, `request/channel/*.java` |

Other **get** requests that exist on this port (names only): `preview` (live; 🌐 go2rtc:
`{"preview":{"audio":["default"],"channels":[0],"resolutions":["HD"]},"method":"get"}`), `talk`,
`image`, `panorama`, `upload{for}`, `usr_def_audio`, `video_call`, `video_call_status`,
`video_call_valid`. URI stream types: `image, preview, download, sdvod, talk, usr_def_audio`
(`common/UriStreamType.java:6-11`).

### 7.7 Notifications from the camera

✅ Seen: `{"type":"notification","params":{"event_type":"stream_status","status":"finished"}}`
(with `X-If-Encrypt: 0`; it carried `X-Session-Id` in the snapshot tests; 🌐 a public capture
shows it without).

📖 Everything the app's clients handle (`src6/bd1/e.java:1037-1102`, `…/control/notification/*.java`,
`common/NotificationEventType.java`):

| `event_type` | Params | Meaning |
|---|---|---|
| `stream_status` | `status`: `finished` \| `grabbed` \| `image_ended` (+ `total_len`, `image_id`) | `finished` = nothing more for this request; `grabbed` = relay stream taken by another client |
| `stream_finish` | `reason`: `finish` \| `interrupt` \| `internal_error` \| `channel_invalid` \| `channel_offline` \| `media_encrypt_changed` \| `password_changed` \| `permission_deny` \| `share_finish` | only `finish` is a clean end |
| `disk_status` | `status:"offline"` | SD card gone → app error `-1104` |
| `connection_closed` | `close_reason` (`server_stop`, …), `error_code` | codes 38-42 only acknowledge the app's own close |
| `playback_switch_next` | `mac`, `streams` | playback moved to the next file |
| `channel_stream_status` | list of `normal` \| `no_data` \| `offline` \| `lack_bandwidth` | |
| others | `internal_error`, `data_limit`, `data_total`, `heartbeat`, `change_aov_type`, `channel_mime_info` | |

After `finished` the app's connection does **not** close: it parks until a new request is
queued (`src6/bd1/e.java:1047-1064`) - the session stays allocated until `do stop` + close.

### 7.8 Teardown ✅

1. If a `session_id` was obtained, send `{"type":"request","seq":<n>,"params":{"stop":"null","method":"do"}}`
   with `X-Session-Id` (frees the camera's session slot). Best effort; do not wait for a reply.
2. Close the TCP socket. No terminating boundary on a local connection.
3. Wait ~1 s before opening the next media session (the web app does so after every clip job).

✅ What the reference really does: **clip** sessions send `do stop`, close, and the worker then
sleeps 1 s (`app/sd.py` `Fetcher._pull()` → `finally: sess.stop()`, `Fetcher._work_loop()` →
`time.sleep(1.0)`); **thumbnail** sessions are simply closed - no `do stop`, no pause
(`app/sd.py` `_Thumbs._loop()`; same in `tapo_media.__main__`, which opens the video session right
after the snapshot session) - and that is the code path the working web app runs, so a missing
stop after snapshots is not fatal. Whether it leaks a session slot for a while is open (§12.3).

📖 The app does steps 1-2 - `do stop` with `X-Session-Id`, then close - on its download and
playback connections (`src6/zb1/b.java:883-913`, `src6/bd1/e.java:1225-1254,1186-1191`) and also
on its image connection (`src5/l61/b.java` k0() sends a `DoStopRequest` with `X-Session-Id`);
the closing boundary `----client-stream-boundary----\r\n` is sent only on P2P (connection
type 16); relay connections send a notification `{"close_reason":"exit","event_type":"connection_closed"}`
instead (other reasons: `request_timeout`, `data_timeout`, `use_high_priority_connection`).
Through its live control client the app waits ≤ 2 s for the stop response (`src5/a41/k0.java:887-893`).

### 7.9 Heartbeat / pre-connection 📖

`X-Preconn: 1` and `X-Hb: 5` in the 401 (✅ seen) only advertise that the camera supports
**idle pre-connections** with a 5 s heartbeat. The app's pre-connection client
(`src6/na1/e.java:134-185`, `src6/o91/l.java:209-268`; port 8800 TCP or 28800 TLS-PSK) sends the
**request** headers `X-Preconn: 1` + `X-Client-UUID: <app uuid>`, reads `X-Hb` (default `15`),
`X-Session-Id` and `Key-Exchange` from the 200, then sends every `X-Hb` seconds:
```
----client-stream-boundary--\r\n
Content-Type: application/json\r\n
Content-Length: 63\r\n
[X-Session-Id: <id>\r\n]
\r\n
{"type": "notification", "params": {"event_type": "heartbeat"}}\r\n
```
The normal streaming clients send neither. ✅ **No heartbeat is needed** for the
request/stream/stop usage of this spec (downloads and a 205 s playback ran without one).

### 7.10 The app's own `POST /stream` head 📖 (the reference's shorter head of §7.2 is what is verified)

```
POST /stream HTTP/1.1
Content-Type: multipart/mixed; boundary=--client-stream-boundary--
User-Agent: <http.agent>
Host: <ip>:8800
Connection: Keep-Alive
Accept-Encoding: gzip
Content-Length: 0
X-Key-Exchange: 1                      (unless the key is already known / TLS)
[Authorization: Digest …]              (second request)
```
(`oa1/a.java:48-61,399-411`.) Socket timeouts 30 000 / 15 000 ms; Digest user `"admin"`.
`X-Client-Model`, `X-Client-Id`, `X-Token` are relay/P2P only.

**Query strings** - only for hub / NVR children or when a `WifiCameraParam` is present; a
directly connected camera uses the bare `POST /stream` ✅ (`src5/y31/d.java:16-176`, `y31/c.java:543-550` = `src5/y31/c.java:557-564`,
`ma1/s1.java:1378-1385`):
```
/stream?deviceId=<id>&type=download&playerId=<uuid>&media_type=<n>[&sample_rate=8&encode_type=G711alaw]
/stream?deviceId=<id>&type=sdvod&playerId=<uuid>&start_time=<epoch>[&event_type=%5B1%2C2%5D][&face_id=][&traj_start_time=][&play_type=][&auto_seek=N][&vod_type=N]
/stream?deviceId=<id>&type=preview&resolution=<r>
/stream?deviceId=<id>&type=talk&mode=<m>&playerId=<uuid>
/stream?playerId=<uuid>&type=image&image_type=<t>&image_format=<f>[&name=&tag=]
/stream?deviceId=<id>&type=usr_def_audio&playerId=<uuid>&audio_type=<t>&name=<n>[&audio_file_id=]
```
(`camera_mac=<mac>` can replace `deviceId=`.) 🌐 pytapo adds the same for children plus an
`X-Client-UUID` header.

### 7.11 Concurrency rules

- ✅ **Keep ONE media session at a time** (clips and thumbnails alike): the camera is fragile
  under load; the web app serialises everything behind one lock (`_media_lock`; a waiting clip
  pre-empts the thumbnail worker via `_clip_waiting`) and sleeps 1 s after every clip job (2 s
  after a failed thumbnail batch, no pause after a successful one). Thumbnails are fetched in
  batches of ≤ 24 on one connection (kept open ≤ 1 s waiting for a follow-up request), then the
  lock is released.
- ✅ Never mix media types on a connection (§7.6.2).
- 🌐 The pytapo author reports that parallel downloads are not possible and that browsing
  recordings in the Tapo app during a download makes the camera stop sending.
- ✅ **`-52405` observed live (2026-09-18):** with two processes pulling clips from the camera at
  the same time (a second server + an automated test next to the owner's browser), the `download`
  request was answered `{"type":"response","params":{"error_code":-52405}}` (`TOO_MANY_REQUEST`,
  "device in use") and playback failed for the user. It cleared by itself within ~1 minute once
  only ONE client remained. A per-process lock is not enough: never run two instances/scripts
  against the media port. The reference service (`app/sd.py`) serialises clips *and* snapshots
  behind one lock, retries busy codes 3× with 4/8/12 s back-off, then reports "Caméra occupée".
- 📖 Session-limit errors to expect when breaking these rules: `-52405`, `-52407`, `-52417`,
  `-52435` (§10.2); the app treats those four as "device in use, retry later"
  (`src6/com/tplink/libtpp2pcommon/util/a.java:152-157`).

---

## 8. Stream payload

### 8.1 Container ✅🧪

- Every `video/mp2t` part decrypts to a whole number of **188-byte MPEG-TS packets** and
  carries **at most ONE access unit**: one video frame, or one 800-byte audio PES (5 TS packets
  = 940 bytes). 🧪 A part never exceeds **345 TS packets (64 860 bytes plaintext,
  `Content-Length: 64864` once PKCS#7-padded** - exactly the first data part shown in §7.4): a
  key frame bigger than that (here 100-190 KB = 547-1008 packets; the first key frame of the
  analysed clip is a 165 026-byte PES) is **continued in the following part(s)**. Never treat a
  part as a complete frame - feed every part, in order, to the TS demuxer (what the reference
  does). The null-PID tags, PAT and PMT travel in the key frame's first part, not in parts of
  their own. Accounting of the 66 s download capture (1713 parts, 10 045 028 bytes): 989 video
  frames + 659 audio PES + 65 key-frame continuation parts (= sum of
  `ceil(key-frame packets / 345) − 1` over the 33 key frames) = 1713. (The per-key-frame packet
  counts come from the offline analysis of that capture; the raw capture files were scratch
  files and are no longer on disk.)
- PAT on PID `0x0000`, **PMT on PID `0x0012`**, PCR PID = video PID. PMT section, identical
  every time:
  ```
  02 b0 17 00 01 f1 00 00 e0 44 f0 00 | 1b e0 44 f0 00 | 90 e0 45 f0 00 | 20 14 66 4a
  ```
  → **video: stream_type `0x1B` (H.264) on PID `0x44`**; **audio: stream_type `0x90` on PID `0x45`**.
- Stream start / every GOP: `null(tag 0)`, `null(UTC tag)`, PAT, PMT, then the key frame.
- Video: **H.264 High, 2304×1296, 15 fps**, GOP = 2 s (30 frames). PES header
  `00 00 01 e0 <len, or 00 00 for key frames > 64 KB> 80 80 05 <5-byte PTS>`, PTS only (no DTS),
  Annex-B NALs; a key frame starts `00 00 00 01 67` (SPS), no AUD.
  🧪 Do not assume every video PES has a PTS: one playback capture that began in the last
  seconds of a recording opened with a key-frame PES `00 00 01 e0 00 00 80 00 00` (no PTS,
  `PES_header_data_length` 0) directly followed by the SPS (1 of its 100 video PES; all others
  `80 80 05`; capture analysed offline, file not kept). Always test `PTS_DTS_flags`
  (`payload[7] & 0x80`) before decoding a PTS, as the reference does (`ClipDemuxer.feed()`:
  `has_pts = len(payload) >= 14 and payload[7] & 0x80`).
- 📖 The app's demuxer maps stream_type `27`=H264, `36`=H265, `15`=AAC, `11`=OPUS, `3/4`=MP3,
  `144 (0x90)`=PCMA, `145 (0x91)`=PCMU, `6`=private with an "Opus" registration descriptor, and
  accepts PES stream_ids `E0, C0, BD, FA, FD` (`src5/com/tplink/libtpdemux/tsdemux/b.java:343-402,558-598`).

### 8.2 Audio ✅🧪

- **G.711 A-law, 8 kHz, mono.** One PES per **100 ms**: header
  `00 00 01 c0 03 28 80 80 05 <5-byte PTS>` then **800 raw A-law bytes** (PES_packet_length
  `0x0328` = 3 + 5 + 800). PTS on every PES, no DTS, **no private header** before the samples.
  Successive PTS differ by 9000 ticks.
- 📖 Sample-rate nibble: the upper nibble of the byte **after the elementary PID** in the PMT ES
  entry (`(entry[3] >> 4) & 15`) can override the rate: `8` ⇒ 16 000 Hz, `11` ⇒ 8000 Hz (AAC-style
  index table); defaults PCMA ⇒ 8000 Hz mono, PCMU ⇒ 16 000 Hz mono (`src5/…/tsdemux/b.java:943-956,1290-1337`).
  Here the entry is `90 e0 45 f0 00` ⇒ nibble `0xF` ⇒ default **8000 Hz**.
- 🧪 A-law (not µ-law) is confirmed by the silence codes: `0xD5`/`0x55` = 92 % of the bytes.
- ffmpeg's mpegts demuxer does not know stream_type `0x90` ⇒ the audio must be extracted
  by hand (§8.5). 🧪 Dead end: rewriting the PMT type to `0x03` and forcing `-c:a pcm_alaw`
  fails ("unspecified sample rate", "Decoder requires channel layout"); `-ar/-ac` are not
  accepted as mpegts input options (ffmpeg 6.1).

### 8.3 THE TRAP - audio and video PTS clocks are not aligned ✅

Within one recording the **audio PTS clock can be offset from the video PTS clock by
SECONDS** (`+2.213 s` and `+4.177 s` observed; other clips ~`+0.05…0.07 s`) **although the
streams are synchronous**: audio parts arrive interleaved from the very first frames and
their `X-Data-PTS` wall-clock headers are within ~40 ms of the video's
(e.g. first parts `1789752472000` (V), `…040` (V), `…040` (A) while the TS PTS say V=1967.010 s, A=1969.223 s).

- Aligning by TS PTS shifts the audio late and makes the **first HLS segment video-only**;
  hls.js then dies with `bufferAppendError` "audio SourceBuffer does not exist".
- **Correct alignment = `X-Data-PTS` of the first audio part − `X-Data-PTS` of the first
  video part** (milliseconds → seconds). The reference clamps it to `[-0.5 s, +1.0 s]` and
  uses 0 outside that range or when a header is missing (`ClipDemuxer.audio_offset`).
- 🧪 An earlier analysis that placed audio by PTS happened to work on a clip whose offset was
  only +70 ms; do not generalise it.

### 8.4 In-band tags on the null PID `0x1FFF` 📖🧪

TS packets on PID `0x1FFF` carry TP-Link private tags; tag = `payload[0]`
(`src5/com/tplink/libtpdemux/tsdemux/b.java:297-340,860-874`):

| Tag | Layout | Meaning |
|---|---|---|
| `0x00` | `00 xx xx ff…` | filler, ignored by the app |
| `0x01` | `01 <2 bytes> <uint64 BE epoch seconds> ff…` - e.g. packet `47 1f ff 11 01 00 01 00 00 00 00 6a ac 7c 4f ff…` ⇒ `1789688911` | **UTC tag**. 🧪 Present in both playback *and* download streams from this camera: once per GOP (every 2 s), right before PAT+PMT+key frame; 33 tags for a 66 s clip, first = the clip's `startTime`. The 2 bytes in between are unknown (seen `0001`, `0660`, `0669`, `064b`…) |
| `0x11` | index in `payload[1]` | panorama index |
| `0x12` | - | **`VOD_STREAM_FINISH`**, treated by the app like the JSON `finished`. 🧪 **Not** emitted at the end of a `download` (the JSON notification is the only end marker there); never seen so far |

📖 The player derives each frame's wall clock as *last UTC tag + PTS delta since that tag*, the
delta resetting when the PTS jumps by > 1 s (`j31/e0.java`). Stop rule for a **playback**
stream: stop once a UTC tag `>= end_time`, or on a UTC discontinuity, or on tag `0x12`, or on
`stream_status finished` / `stream_finish(reason=finish)` - a cut at a UTC tag is a clean
key-frame cut. With `download` none of this is needed.

### 8.5 Demuxing algorithm ✅ (`tapo_media.ClipDemuxer`)

For every 188-byte packet (`0x47` sync; drop packets that lost sync):
1. `pid = ((b1 & 0x1F) << 8) | b2`; `pusi = b1 & 0x40`; adaptation field present if `(b3>>4) & 2`
   (skip `1 + b4` bytes); payload present if `(b3>>4) & 1`.
2. On `pusi` with payload starting `00 00 01`: `stream_id 0xC0-0xDF` ⇒ this PID is **audio**,
   `0xE0-0xEF` ⇒ **video**. If the PES has a PTS (`payload[7] & 0x80`), decode the 33-bit PTS
   from `payload[9:14]`; remember the first video / first audio PTS **and the `X-Data-PTS` of
   the part they came in**. For audio strip the PES header: `payload = payload[9 + payload[8]:]`.
3. Audio PID ⇒ append the payload bytes to the raw A-law sink. **Everything else** (PAT, PMT,
   video, null packets) ⇒ pass the packet through unchanged: that is a valid video-only TS for ffmpeg.
4. Video duration so far = `(last_video_pts − first_video_pts) mod 2^33 / 90000` (handles PTS wrap).

### 8.6 ffmpeg recipes

✅ **Streaming (what the web app runs)**: video TS on stdin, raw A-law on a second pipe, one
process, two outputs (HLS *event* playlist for immediate playback + faststart MP4 as the kept copy):
```
ffmpeg -nostdin -loglevel error -y \
  -f mpegts -i pipe:0 \
  -itsoffset <audio_offset_seconds, 3 decimals> -f alaw -ar 8000 -ac 1 -i pipe:<fd> \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -ar 16000 -ac 1 -b:a 48k \
  -f hls -hls_time 2 -hls_playlist_type event -hls_flags independent_segments+temp_file \
      -hls_segment_filename <dir>/seg_%05d.ts <dir>/index.m3u8 \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -ar 16000 -ac 1 -b:a 48k \
  -movflags +faststart -f mp4 <out>.mp4
```
Operational details that matter:
- `-itsoffset` must be known **when ffmpeg starts**: buffer the first parts until the first
  audio part has arrived (or 1.5 s of video without audio → no audio input at all), then
  launch ffmpeg and flush the buffers.
- Pass the audio read-fd with `pass_fds`; feed **each pipe from its own thread/queue** so the
  network reader never blocks on ffmpeg (a single writer deadlocks).
- Close both pipes at the end → ffmpeg writes `#EXT-X-ENDLIST` and the `moov`.
- Without audio: drop the second input, `-map 1:a:0` and the audio codec options.

**From files** - the streaming command's options applied to the two files written by
`python -m tapo_v4.tapo_media` (this is what §9.1 runs):
```
ffmpeg -y -f mpegts -i clip.ts -itsoffset <offset> -f alaw -ar 8000 -ac 1 -i clip.alaw \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -ar 16000 -ac 1 -b:a 48k -movflags +faststart clip.mp4
```
🧪 The file command that was validated offline was a *different* one:
`ffmpeg -hide_banner -loglevel warning -y -fflags +genpts -i rec1.video.ts -f alaw -ar 8000 -ac 1 -i rec1.alaw -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 32k -shortest -movflags +faststart rec1.mp4`,
fed with audio that a splitter had already placed on the video timeline (silence-padded, 70 ms
on that clip - the PTS placement that §8.3 warns against), hence no `-itsoffset`;
`-ar 16000 -b:a 48k` on the output was tested OK too.
🧪 Also validated offline: a fragmented-MP4 pipe output
(`-movflags frag_keyframe+empty_moov+default_base_moof -f mp4 pipe:1`). Use `-f mulaw` and the
PMT-nibble rate if a camera ever announces stream_type `0x91`.

---

## 9. End-to-end recipes

Run from `~/tapo-web` with `.venv/bin/python`. Import only `tapo_v4.tapo_v4` / `tapo_v4.tapo_media`
(**not** `app.sd` / `app.main`: importing `app.sd` creates the `recordings/sd` and HLS `sdplay`
directories and starts three daemon threads - thumbnail worker, fetch worker, reaper;
`app.main` builds the FastAPI app whose lifespan calls `sd.startup()`, which wipes the live HLS
output and the partial MP4s - at server start, not at import).

### 9.1 List days → list clips → thumbnails → download → MP4

```python
import datetime as dt, os, subprocess, time
from zoneinfo import ZoneInfo
from dotenv import dotenv_values
from tapo_v4.tapo_v4 import TapoV4
from tapo_v4.tapo_media import (PLAYER_ID, ClipDemuxer, MediaSession,
                            fetch_snapshot, stream_clip)

env  = dotenv_values(".env")
HOST, PWD = env["TAPO_HOST"], env["TAPO_CLOUD_PASSWORD"]

# -- control API (logs in on first call, re-logs in once if the session died)
c = TapoV4(HOST, PWD)                                   # username "admin"
print(c.get_sd_status()["status"])                      # -> "normal"
tz   = ZoneInfo(c.get_clock()["zone_id"])               # "Europe/Brussels"
days = sorted(c.search_days("20260101", "20261231"))    # ["20260701", ...]; sort it yourself (app/sd.py does)
day  = dt.datetime.strptime(days[-1], "%Y%m%d").replace(tzinfo=tz)
lo, hi = int(day.timestamp()), int((day + dt.timedelta(days=1)).timestamp()) - 1
clips = c.search_videos_utc(lo, hi, PLAYER_ID)          # [{"startTime","endTime","video_type":"2"}, ...]
start, end = int(clips[0]["startTime"]), int(clips[0]["endTime"])

# -- thumbnails: ONE media session, snapshots only, one after the other
with MediaSession(HOST, PWD, timeout=8.0) as sess:
    for clip in clips[:5]:
        jpg = fetch_snapshot(sess, int(clip["startTime"]))          # 640x360 JPEG bytes or None
        if jpg:
            open(f"/tmp/thumb_{clip['startTime']}.jpg", "wb").write(jpg)
    sess.stop()                                         # optional: the reference closes thumbnail sessions without it (§7.8)
time.sleep(1.0)                                         # let the camera release the media session

# -- clip: a SEPARATE media session (a connection is bound to its first media type)
with open("/tmp/clip.ts", "wb") as fv, open("/tmp/clip.alaw", "wb") as fa, \
        MediaSession(HOST, PWD, timeout=20.0) as sess:
    demux = ClipDemuxer(fv.write, fa.write)
    try:
        clean = stream_clip(sess, start, end, demux)    # True = camera said "finished"
    finally:
        sess.stop()                                     # frees the camera's session slot
print(clean, demux.video_seconds, demux.audio_bytes / 8000, demux.audio_offset)

# -- MP4 (audio aligned with the X-Data-PTS rule, NOT the TS PTS)
cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "mpegts", "-i", "/tmp/clip.ts"]
if demux.audio_bytes:
    cmd += ["-itsoffset", f"{demux.audio_offset:.3f}", "-f", "alaw", "-ar", "8000", "-ac", "1",
            "-i", "/tmp/clip.alaw", "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-ar", "16000", "-ac", "1", "-b:a", "48k"]
else:
    cmd += ["-map", "0:v:0", "-c:v", "copy"]
subprocess.run(cmd + ["-movflags", "+faststart", "/tmp/clip.mp4"], check=True)
```

### 9.2 One-liners

```bash
cd ~/tapo-web
.venv/bin/python -m tapo_v4.tapo_media <startTime> <endTime> /tmp/clip    # -> clip.jpg + clip.ts + clip.alaw, prints the offset
.venv/bin/python -m pytest tests/test_tapo_media.py tests/test_tapo_v4_ds.py -q   # 12 offline protocol tests (fake /ds camera, fake Streamd, synthetic TS); no camera, no app.sd import
.venv/bin/python -m pytest tests -q                                             # everything; tests/test_sd.py imports app.sd (starts its worker threads, still no camera traffic)
```

### 9.3 Minimal `/ds` call without the helper class

```python
import json, struct
from Crypto.Cipher import AES
# after c.login():  c.stok, c.seq (= start_seq), c.key (16 B), c.nonce0 (12 B)
inner = json.dumps({"method": "multipleRequest", "params": {"requests": [
    {"method": "getDeviceInfo", "params": {"device_info": {"name": ["basic_info"]}}}]}},
    separators=(",", ":")).encode()
seq = c.seq; c.seq += 1
seq &= 0xFFFFFFFF                                  # signed Java int on the camera side (§5.1)
e = AES.new(c.key, AES.MODE_CCM, nonce=c.nonce0[:8] + struct.pack(">I", seq), mac_len=16)
body = struct.pack(">I", seq) + e.encrypt(inner) + e.digest()
r = c.session.post(f"{c.base}/stok={c.stok}/ds", data=body, timeout=10,
    headers={**c._headers(), "Content-Type": "application/octet-stream",
             "Accept": "application/octet-stream"})   # exactly the verified header set (§5.5), Referer included
raw = r.content                                   # b'{"error_code":...}' = refused (session dead)
rs = struct.unpack(">I", raw[:4])[0]
d = AES.new(c.key, AES.MODE_CCM, nonce=c.nonce0[:8] + struct.pack(">I", rs), mac_len=16)
print(json.loads(d.decrypt_and_verify(raw[4:-16], raw[-16:])))
```

---

## 10. Error code tables

### 10.1 Control API

| Code | Name / meaning | Status |
|---|---|---|
| `0` | success | ✅ |
| `-40106` | `UNSUPPORTED_METHOD` (`common/CameraErrorCode.java:26`) - by its name, the code to expect per sub-request for an unknown method | 📖 |
| `-40109` | `ONE_SECOND_REPEAT_REQUEST` (`common/CameraErrorCode.java:27`) - by its name the firmware has a repeat-request limiter: do not poll | 📖 |
| `-40209` | `INVALID_ARGUMENTS` (app debug enum, §5.3; 🌐 python-kasa uses the same name, pytapo / ioBroker call it "Invalid login credentials") - at login: unknown username; on `/ds`: decrypted fine but the inner request is not a `multipleRequest` | ✅ |
| `-40210` | `PROTOCOL_FORMAT_ERROR` (the media layer names it `METHOD_DO_NOT_EXIST`) | 📖 |
| `-40211` | `MISSING_NECESSARY_PARAMS` - what **V3** clients (pytapo / python-kasa) get at login | ✅ |
| `-40401` | `SESSION_EXPIRED` - on `/ds`: wrong seq or undecryptable body; **the session is dropped** | ✅ |
| `-40404` / `-40408` | `DEVICE_BLOCKED` / `SYSTEM_BLOCKED` (`common/CameraErrorCode.java:17,21`) - device / system blocked (too many bad logins); back off for minutes | 📖 exists, not triggered |
| `-40409` / `-40414` | `NONCE_EXPIRED` / `NEED_LOGIN_BY_LOCAL_PASSWORD` (`common/CameraErrorCode.java:22,29`) - login codes of the enum, never seen here (V3-era by their names) | 📖 |
| `-40413` | `INVALID_NONCE` - the expected reply to a V3 nonce request (irrelevant here) | 📖 |
| `-40418` | `TPAP_AUTHENTICATION_FAILED` | 📖 |
| `-40420` | `TPAP_SLP_AUTH_TAG_SIG_FAIL` (AEAD tag failure; this camera answers `-40401` instead) | 📖 |
| `-40421` | `TPAP_SESSION_TOKEN_INVALID` - stok not accepted as a token; seen only for a percent-encoded stok (a garbage well-formed stok gave `-40401`, §5.3) | ✅ (`TESTS.md` B2) |
| `-71101` / `-71102` / `-71103` | `USER_ID_FULL` / `USER_ID_EMPLOYED` / `USER_ID_INVALID`. `-71103`: `searchVideoWithUTC` called with `"id"` instead of `"player_id"` on a playback-v6 camera | `-71103` ✅, others 📖 |
| `-71105` | 🌐 pytapo: refresh the user id and retry | 🌐 |
| `-2402`, `-2004`, `-2001`, `-2101` | app-internal TLA codes that trigger its single re-login (`hm1/a0.java:111-120`) | 📖 |

### 10.2 Media port (stream layer) 📖

Arrive in a response's `params.error_code`, or as the JSON body of an **HTTP 503** to the POST
(`com/tplink/libtpappcommonmedia/exception/MediaException.java:4-96`, `src6/bd1/e.java:845-884,1106-1163`).
None was triggered live.

| Code | Name | Meaning / app reaction |
|---|---|---|
| `-52402` | `VOD_INVALID_REQUEST` | invalid request (UI ignores it) |
| `-52405` | `TOO_MANY_REQUEST` | "device in use" |
| `-52407` | `TOO_MANY_CLIENT` | too many viewers (download client reacts specially) |
| `-52409` | `SD_CARD_UNPLUGGED` (also `TOO_MANY_USR_ITEM`) | |
| `-52411` | `TALK_IS_USED` | |
| `-52417` | `VOD_SESSION_OCCUPIED` | retryable; "playback/download expired" or "device in use" |
| `-52419` | `TOO_MANY_HTTPS_CLIENT` | |
| `-52422` | `SD_CARD_UNUSABLE` | |
| `-52423` | `AUDIO_PARAMS_INVALID` | |
| `-52435` | `VOD_SESSION_FULL` | retryable |
| `-52499` | `VIDEO_CALL_BUSY` | |
| `-52212` | `FLOW_UPPER_LIMIT_REACHED` | |
| `-1104` | `SD_CARD_OFFLINE` | from the `disk_status` notification |
| `-2001` | `STREAM_DATA_DECRYPT_ERROR` | |
| `-10002` | `INVALID_DATA` | `finished` received without any video PTS |
| `-3` / `401` | `DIGEST_AUTHORIZE_FAIL` / `UNAUTHORIZED` | reference: a second 401 is reported as a wrong cloud password (not triggered live, §7.2) |
| `-40210` | `METHOD_DO_NOT_EXIST` | |
| `-71101…-71103` | user-id errors (`client_id`) | |
| `-2031…-2036`, `-2099`, `-100005`, `-100006` | client-side socket / relay timeouts | |

---

## 11. Pitfalls & operational rules

1. **A refused `/ds` kills the session** (`-40401` once ⇒ every later request fails). Re-login
   **once**, never in a loop - login lockouts (`-40404` / `-40408`) exist.
2. **Never put the 24-byte TSLP frame in front of a `/ds` body**; never send a bare method.
3. **stok goes raw into the URL.** Percent-encoding it ⇒ `-40421`.
4. **One `/ds` request at a time** per session (seq must stay ordered); one seq per request, never reused.
5. **The camera's Wi-Fi flaps** and it degrades under load: on `No route to host` / TLS timeouts
   wait 10-30 s; cache listings; do not poll. A power cycle clears transient lockouts.
6. **ONE media session at a time**; after a clip send `do stop`, close, and wait ~1 s before the
   next session (the web app closes thumbnail sessions without `do stop` and without a pause -
   tolerated, §7.8).
7. **A media connection is bound to its first media type**: thumbnails and video on separate connections.
8. **Use `download`, not `playback`**, to fetch clips (10× faster, stops at `end_time`, full
   frame rate + audio). `scale > 1` is a key-frame-only fast-forward without audio.
9. **Align audio with `X-Data-PTS`, never with the TS PTS** (§8.3) - otherwise HLS breaks and
   MP4s have late audio.
10. ffmpeg cannot read the audio from the TS (stream_type `0x90`): split it out (§8.5).
11. Use the camera's `zone_id` for day boundaries; `timezone` is the non-DST offset.
12. Types are inconsistent on purpose - keep them: listing `start_time` = int, media
    `start_time` = string; `video_type` = string, `vedio_type` = int; SD sizes = strings with a `B` suffix.
13. Nothing in this spec writes to the SD card or to the camera configuration. `setLocalCtrl`
    would overwrite the PAKE verifier - do not call it.
14. Do not run the Tapo app's recording browser during a download 🌐 (it interrupts the stream).
15. 🌐 Alternative that avoids V4 altogether (reported fix for `-40211` on several 1.3.x/1.4.x
    firmwares, not tried here): in the Tapo app toggle *Me → Tapo Lab / Third-Party Services →
    Third-Party Compatibility* OFF then ON while on the camera's LAN; stock pytapo (V3) may then log in.

---

## 12. Provenance

### 12.1 How each part was established

| Part | How |
|---|---|
| §1-§4 login | Reverse-engineered from the app (`em1/a.java`, `em1/b.java`, `jl1/*.java`, `kl1/*.java`, `j2.java`), then **proven live**: `dev_confirm == HMAC(KcB, X)` (`TESTS.md` A7-A11). |
| §5 `/ds` | Found by re-reading the app's **HTTP** path (`hm1/a0.java`, `SecSessionCipher.java`, `lu0/dk.java`) instead of its TCP framing; three controlled live probes, fresh login each (`TESTS.md` D1-D3): garbage → `-40401`; bare method → `-40209`; `multipleRequest` → encrypted reply. |
| §6 methods | Live probes (`TESTS.md` D4) - responses in this file are the real decrypted ones; tables of §6.2-6.4 from `PlayBackBaseRepository.java`, `lu0/dk.java`, the `model/*` classes. |
| §7 media port | Wire format from pytapo 🌐, confirmed live; `download` request, acks, stop from `zb1/b.java`, `z31/a.java`, `GetDownloadParams.java`; live tests `TESTS.md` D5-D9. |
| §8 payload | Live captures parsed offline (PMT, PES, tags); the PTS trap found by comparing TS PTS with `X-Data-PTS` of the first parts of a clip whose HLS playback failed; ffmpeg recipe = `app/sd.py`. |
| 📖 items | Two static-analysis campaigns over the decompiled app 3.21.111 (control channel: payload path, OkHttp client, SPAKE2+ params, cipher, IoT cross-check, prior art; media: download protocol, playback control, audio format, thumbnails/types, prior art). |

### 12.2 The old TSLP-frame mistake

Until 2026-09-18 the client wrapped the `/ds` body in the 24-byte frame of `dm1/a.java`
(§5.7) and used `seq = start_seq + 1` (`incrementAndGet`, `session/d.java:78`). Both belong to
the app's **netty TCP/BLE** transport. Over HTTP the camera read the frame's first bytes
`01 02 02 00` as seq `0x01020200` ⇒ `-40401`, for every one of ~60 variations - which was
misread as "the camera rejects before decrypting". The single test that had the right
framing (`seq ‖ ct ‖ tag`) carried a bare method ⇒ `-40209`, misread as "malformed". The
error codes actually mean: `-40401` = seq/decryption failed, `-40209` = decrypted, shape
refused. The historical matrix is kept in `TESTS.md` §B2 (its "rules out" column is wrong).

### 12.3 Open questions (nothing below blocks the working client)

- Does the raw TDP discovery reply (or `sub_method: discover`) of this camera contain a `tpap`
  object? python-kasa showed none, yet the app only takes this path when it exists.
- Do the app-exact login variants (hashed username, `encryption` list, stok reuse) behave
  differently from the literal `admin` login? Literal `admin` gives a fully working session.
- Exact seq window: how far forward may seq jump, and is a replayed seq rejected with `-40401`?
- Meaning of the 2 bytes before the UTC value in tag `0x01`, and of the filler tag `0x00`.
- Does any firmware path emit tag `0x12` or the notifications `stream_finish` / `playback_switch_next`?
- Are `X-Stream-Type` / `X-Data-PTS-Ext` ever sent by this camera?
- Does closing the socket without `do stop` leak a session slot, and for how long?
- Can a finished download connection be reused for the next `get download` (the app does it)?
- Does `searchDetectionList` return per-event types (person / pet / vehicle) on this camera,
  and is `snapshot_enable` true without a Tapo Care subscription?

### 12.4 Section map (old → new), for cross-references in the other HANDOFF files

| Old | New |
|---|---|
| §0 summary, fixed headers | §0, §5.5 |
| §1-§4 | §1-§4 (unchanged numbering; formulas verbatim) |
| §5 business channel | §5 |
| §6 SD-recording methods | §6 |
| §6b media port | §7 (protocol) + §8 (payload) |
| §7 reproduce | §9 |
| §8 error codes | §10 |
