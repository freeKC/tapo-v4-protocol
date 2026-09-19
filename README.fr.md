# Caméras Tapo : le nouveau protocole local ("V4", SPAKE2+)

[English version](README.md)

Après une mise à jour du firmware (1.3.4), ma Tapo C510W a cessé de répondre à pytapo, python-kasa
et Home Assistant. Chaque tentative de connexion renvoyait `error_code -40211`. La découverte
réseau annonce `encrypt_type: ["4"]`, et rien de public ne parle encore ce protocole.

J'ai passé un bon moment à fouiller l'appli Android officielle et à interroger la caméra jusqu'à ce
qu'elle réponde. Ce dépôt en est le résultat : une description complète du protocole et un petit
client Python qui fonctionne vraiment avec ma caméra. Le même symptôme est signalé sur C51A 1.3.4,
C220 1.4.4, C100 1.4.3/1.5.1 et C125 1.4.2, c'est sans doute la même histoire.

Ce qu'on trouve ici :

* [`PROTOCOL.md`](PROTOCOL.md) : la spécification, à l'octet près (en anglais). C'est long, mais
  tout y est. Chaque affirmation précise si je l'ai vérifiée sur la vraie caméra ou seulement lue
  dans le code de l'appli.
* [`tapo_v4/tapo_v4.py`](tapo_v4/tapo_v4.py) : la connexion (SPAKE2+ sur P-256) et le canal chiffré
  `/stok=<stok>/ds` (AES-128-CCM). Les maths elliptiques sont en Python pur, il ne faut que
  `requests` et `pycryptodome`.
* [`tapo_v4/tapo_media.py`](tapo_v4/tapo_media.py) : le port média (8800). Authentification digest,
  flux multipart chiffré AES-CBC, téléchargement des clips de la carte SD, vignettes, et un petit
  démultiplexeur MPEG-TS pour l'audio.
* [`tests/`](tests) : des tests hors ligne avec une fausse caméra et un faux serveur média.
* [`examples/list_and_download.py`](examples/list_and_download.py) : liste le contenu de la carte SD
  et récupère le dernier clip en MP4.

## En résumé

**La connexion** se fait en deux `POST /`, `pake_register` puis `pake_share`. C'est du SPAKE2+ avec
les points M et N standards de la RFC 9383. L'utilisateur est la chaîne littérale `admin`, le
secret PAKE est `md5_hex(mot de passe cloud)`, et le détail qui m'a pris une éternité : le contexte
du transcript est `SHA256("PAKE V1" || user_random || dev_random)`, pas les octets bruts. La caméra
renvoie un `dev_confirm` qui permet de vérifier ses clés avant d'aller plus loin.

**Les requêtes** partent vers `POST /stok=<stok>/ds` en `application/octet-stream`. Le corps, c'est
simplement `uint32_be(seq) || chiffré || tag16`. Rien d'autre. L'appli possède aussi une trame
"TSLP" de 24 octets avec un CRC, mais elle sert à son transport TCP. Si on la met devant en HTTP, la
caméra lit `0x01020200` comme numéro de séquence et répond `-40401` à tout. J'y ai perdu une journée
entière. Le premier `seq` est le `start_seq` reçu à la connexion. La clé et le nonce viennent d'un
HKDF-SHA256 sur la clé partagée (sels `tp-kdf-salt-aes128-key` et `tp-kdf-salt-aes128-iv`), le nonce
vaut `base[0:8] || uint32_be(seq)`.

**Le JSON à l'intérieur doit être un `multipleRequest`**, même pour un seul appel. Un
`{"method":"getDeviceInfo",...}` tout nu est bien déchiffré par la caméra, et quand même refusé avec
un `-40209` en clair. À savoir aussi : toute requête `/ds` refusée tue la session, il faut se
reconnecter avant de réessayer.

Après ça, toutes les méthodes habituelles fonctionnent comme avant.

**Téléchargement de la carte SD, beaucoup plus rapide.** pytapo demande du `playback` au port
média, que la caméra cadence à la vitesse réelle et qui ne s'arrête jamais à `end_time`. L'appli
officielle utilise une autre requête, `download`. Avec mon Wi-Fi, un clip de 66 s arrive en 7 s
environ, à pleine cadence d'images et avec le son, et la caméra envoie `stream_status: finished` à
la fin. Avec `media_type: 2`, la même requête renvoie la vignette JPEG d'un enregistrement. Il y a
aussi un piège avec les horodatages audio et vidéo, décrit dans la spec (se fier à l'en-tête
`X-Data-PTS`, pas aux PTS du flux TS).

## Essayer

```bash
pip install requests pycryptodome python-dotenv pytest
printf 'TAPO_HOST=192.168.0.50\nTAPO_CLOUD_PASSWORD=mot de passe du compte TP-Link\n' > .env
python examples/list_and_download.py
python -m pytest tests -q        # pas besoin de caméra
```

## Limites

* Testé sur une seule caméra (C510W matériel 2.0, fw 1.3.4 Build 260523). Si vous essayez sur un
  autre modèle, ouvrez un ticket pour me dire ce que ça donne.
* L'appli connaît d'autres variantes de connexion (noms d'utilisateur hachés, réutilisation de
  session, certificats sur les aspirateurs robots par exemple). J'ai noté ce que j'ai vu dans le
  code, mais ma caméra n'en a pas eu besoin.
* Une seule session média à la fois. La deuxième reçoit `-52405` ("appareil occupé").
* À utiliser sur vos propres appareils. Sans lien avec TP-Link.

Le format du port média a d'abord été documenté par [pytapo](https://github.com/JurajNyiri/pytapo), merci à eux.

J'ai aussi fait une petite appli web par-dessus (direct, carte SD, détection d'animaux) :
[tapo-web](https://github.com/freeKC/tapo-web).

Mots-clés : API locale TP-Link Tapo, erreur -40211 Tapo, "Invalid authentication data", caméra Tapo
Home Assistant ne se connecte plus, télécharger les enregistrements de la carte SD Tapo, Tapo sans cloud.

Licence MIT.
