# FarNVR

Otevřený webový záznamový systém (NVR) pro IP kamery s RTSP a ONVIF (otestováno s kamerami Uniview).
Běží na Ubuntu 24.04 LTS, záznamy ukládá na NAS (NFS) a přehrává je v prohlížeči na PC, tabletu i mobilu.

*English summary: self-hosted open-source web NVR for RTSP/ONVIF IP cameras (tested with Uniview). Records H.265 streams without re-encoding
to a NAS, shows live grid and recordings with a gap/motion timeline, 1–8× speed, jog wheel, MP4 export.
UI in Czech and English. See sections below (Czech).*

## Funkce

- **Živý náhled** – mřížka 1 / 2×2 / 3×3 / 4×4. Kamery lze skrýt (jen v zobrazení, nahrávání běží dál)
  a přeřadit šipkami nebo přetažením. Rozložení se ukládá k uživateli.
  Dvojklik nebo ⤢ otevře detail v plné kvalitě se zvukem.
- **Ukazatel záznamu pod každou kamerou** (posledních 24 h): zelená = záznam, červená = chybí,
  oranžová = pohyb. Kliknutím do ukazatele se spustí přehrávání od daného času.
- **Přehrávání záznamů**:
  - kalendář, ve kterém jsou zvýrazněné dny se záznamem,
  - časový rozsah od–do,
  - denní osa a podrobná osa (posuvník) s mezerami a pohybem,
  - rychlost 1× 2× 3× 4× 8×, krokování po snímcích,
  - **virtuální kolečko (jog)** ovladatelné myší, kolečkem myši i dotykem; citlivost 2 s / 30 s / 5 min na otáčku,
  - snímek obrazovky (PNG), označení výřezu `[` `]` a **export do MP4**.
- **Pohyb** – události z kamer přes ONVIF se zobrazují na osách. Kamery v režimu `motion`
  ukládají jen okolí pohybu (10 s před a 20 s po), ostatní nahrávají nepřetržitě.
- **Retence** – mazání záznamů starších než nastavený počet dní a ochrana proti zaplnění disku.
- **Zabezpečení** – HTTPS (Let's Encrypt), přihlášení heslem (Argon2), volitelně dvoufázové ověření (TOTP),
  ochrana proti hádání hesel. Kamery nejsou z internetu vidět, vše jde přes server.
- **Jazyk** – čeština (výchozí) a angličtina. Aplikaci lze na mobilu „přidat na plochu“.

## Jak to funguje

```
 Lokalita s kamerami                    Server (vnitřní síť za firewallem)
 ┌──────────────┐  RTSP + ONVIF   ┌────────────────────── Ubuntu 24.04 server ──────────────────────┐
 │ Kamery 1..N  │ ───────────────►│ go2rtc  ── 1 spojení na stream, živý obraz pro prohlížeč        │
 │ (přístup jen │                 │   │                                                             │
 │  ze serveru) │                 │   ▼                                                             │
 └──────────────┘                 │ nvr (FastAPI) ── ffmpeg: H.265 kopie bez překódování ──► NAS    │
                                  │   │  index úseků (SQLite), pohyb (ONVIF), retence, export       │
                                  │   ▼                                                             │
                                  │ Caddy (HTTPS 443) ◄──── prohlížeč PC / mobil (vlastní doména)   │
                                  └─────────────────────────────────────────────────────────────────┘
```

**Kamery do úložiště samy nezapisují, nahrávání řídí server.** Ten si od každé kamery bere RTSP stream
a ffmpeg ho ukládá po 6sekundových úsecích (fMP4/HLS) bez překódování, takže procesor skoro nezatěžuje.
Každý úsek se zapíše do databáze s přesným časem. Z databáze se pak kreslí ukazatel mezer
a sestavuje přehrávání libovolného úseku.

Kamera musí mít jen správně nastavené streamy, čas (NTP) a detekci pohybu (viz níže).

## Kapacita úložiště

Potřebné místo = datový tok × počet kamer × počet dní. Orientačně:

| Datový tok kamery | 1 kamera / den | 4 kamery, 14 dní | 8 kamer, 14 dní |
|---|---|---|---|
| 0,5 Mbit/s | 5,4 GB | 300 GB | 605 GB |
| 1,0 Mbit/s | 10,8 GB | 605 GB | 1,2 TB |
| 2,0 Mbit/s | 21,6 GB | 1,2 TB | 2,4 TB |

H.265 s chytrým kódováním (u Uniview U-Code) a stropem kolem 1 Mbit/s dává při Full HD obvykle průměr
0,4–0,8 Mbit/s podle ruchu ve scéně. Kamery v režimu `motion` zaberou zlomek. Aktuální denní přírůstek
a odhad kapacity ve dnech ukazuje **Nastavení → Stav systému**. Když místo dojde, nejstarší záznamy
se smažou dřív, ale nahrávání se nezastaví.

## 1. Nastavení kamer (příklad pro Uniview)

Ve webovém rozhraní každé kamery (u jiných značek obdobně):

| Kde | Nastavení |
|---|---|
| **Video → Hlavní stream** | H.265, 1920×1080, 15 fps (stačí i 12), VBR, max. **1024 kb/s**, I-frame interval **30** (2× fps), U-Code: zapnuto (Basic) |
| **Video → Sub stream** | **H.264**, 640×360 (nebo 720×576), 10 fps, 384–512 kb/s – kvůli kompatibilitě náhledů |
| **Audio** | zapnout vstup zvuku; kodek AAC, pokud ho kamera nabízí, jinak G.711U (NVR převede do AAC) |
| **Čas** | NTP zapnuto (např. `tik.cesnet.cz` nebo `pool.ntp.org`), časové pásmo Praha. Bez správného času nefunguje ONVIF přihlášení |
| **Síť → ONVIF** | ONVIF zapnuto, ověřování *Digest/WSSE*; doporučený samostatný účet jen pro NVR |
| **Události → Detekce pohybu** | zapnout, nastavit oblast a citlivost; je to zdroj pohybu na časové ose i pro režim `motion` |
| **Úložiště (SD karta)** | volitelně nechat nahrávat na SD kartu jako zálohu při výpadku linky |

**Kamery v jiné lokalitě**: přesměrujte porty na routeru lokality (pro každou kameru zvlášť) a povolte přístup jen z veřejné IP serveru (nebo lépe použijte VPN):
- RTSP (kamera 554) → např. veřejný port 5541, 5542, …
- HTTP/ONVIF (kamera 80) → např. 8081, 8082, …

RTSP cesty Uniview jsou `/unicast/c1/s0/live` (hlavní) a `/unicast/c1/s1/live` (sub).
U jiných značek se cesty liší (viz dokumentace kamery). Po instalaci se dá spojení ověřit příkazem `docker compose exec nvr nvr-cli check`.

## 2. NAS – sdílená složka přes NFS (příklad Synology)

1. **Ovládací panel → Sdílená složka → Vytvořit**: název `nvr`. **Vypnout Koš** (smazané záznamy by jinak plnily disk),
   nešifrovat, nezapínat indexování.
2. **Ovládací panel → Souborové služby → NFS**: povolit NFS (v4.1).
3. Sdílená složka `nvr` → **Upravit → Oprávnění NFS → Vytvořit**:
   hostitel = IP Ubuntu serveru, oprávnění **Čtení/zápis**, squash **Mapovat všechny uživatele na admin**,
   zabezpečení `sys`, povolit asynchronní zápis.
4. Na serveru:

```bash
sudo apt install -y nfs-common
sudo mkdir -p /mnt/nvr
echo "IP_NAS:/volume1/nvr  /mnt/nvr  nfs4  rw,hard,noatime,_netdev,nofail  0 0" | sudo tee -a /etc/fstab
sudo mount -a && df -h /mnt/nvr
```

## 3. Instalace serveru (Ubuntu 24.04)

Doporučený hardware: 4 jádra CPU, 8 GB RAM, 32 GB SSD pro systém a databázi. Výkon CPU je potřeba hlavně
na převod do H.264 pro prohlížeče bez podpory H.265.

```bash
# Docker
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER   # odhlásit / přihlásit

# Aplikace
git clone <repozitář> && cd <repozitář>/nvr
cp config.example.yaml config.yaml      # kamery, retence
cp .env.example .env                    # doména, hesla kamer
chmod 600 .env
mkdir -p data/nvr data/go2rtc && sudo chown -R 1000:1000 data

docker compose build
docker compose run --rm nvr nvr-cli storage-init     # označí NAS jako úložiště záznamů
docker compose up -d

# Uživatelé; --totp zapne dvoufázové ověření
docker compose exec nvr nvr-cli user add jan --totp
docker compose exec nvr nvr-cli user add petra --totp
```

Soubor `.nvr-storage` v kořeni NAS je pojistka: když se NFS nepřipojí, NVR nenahrává na lokální disk
serveru a v rozhraní ukáže varování.

### Firewall

| Směr | Port | Účel |
|---|---|---|
| internet → server | TCP 80, TCP 443 (+ UDP 443) | webové rozhraní, certifikát Let's Encrypt |
| server → kamery | RTSP a HTTP porty kamer | stream a ONVIF události |
| internet → server | TCP/UDP 8555 | **jen** pokud zapnete `live.webrtc: true` |

DNS: A záznam domény (např. `kamery.example.cz`) na veřejnou IP serveru.

## 4. Ovládání

- **Živě** – rozložení tlačítky `1 / 2×2 / 3×3 / 4×4`, **Kamery** = zobrazit/skrýt a pořadí.
  Pruh pod obrazem ukazuje posledních 24 hodin záznamu, kliknutím přehrajete daný okamžik.
- **Záznamy** – vyberte kameru, den v kalendáři (zelené dny mají záznam) a čas od–do → **Zobrazit**.
  - Klik nebo tažení po ose přesune přehrávání. Mezery se při přehrávání přeskakují.
  - **Kolečko**: táhněte prstem nebo myší dokola (po směru hodin = vpřed), funguje i kolečko myši.
    Klik do středu mění citlivost.
  - Klávesy: `mezerník` přehrát/pauza, `←/→` o snímek (při pauze), `1–5` rychlost.
  - **Export**: označte začátek `[` a konec `]` a klikněte na Export. Formát H.264 je vhodný pro starší přehrávače.

## 5. Podporované prohlížeče

Záznam je v H.265, protože ten šetří nejvíc místa. Prohlížeč, který H.265 neumí, dostane video
automaticky převedené do H.264 (v rohu se zobrazí „Režim kompatibility“).

| Prohlížeč | Záznamy | Živě |
|---|---|---|
| Safari macOS / iPhone / iPad | nativně H.265 | ✓ |
| Chrome / Edge Windows, macOS, Android (s HW dekodérem) | nativně H.265 | ✓ |
| Firefox, starší zařízení, Linux | převod do H.264 na serveru | náhledy ✓ (H.264), detail podle podpory |

## 6. Správa

```bash
docker compose logs -f nvr                  # logy
docker compose exec nvr nvr-cli user list
docker compose exec nvr nvr-cli user passwd jan
docker compose exec nvr nvr-cli user totp jan [--off]
docker compose exec nvr nvr-cli check       # dostupnost kamer
docker compose exec nvr nvr-cli reindex     # obnova indexu z NAS (např. po ztrátě data/)
git pull && docker compose up -d --build    # aktualizace
```

- **Zálohujte** `config.yaml`, `.env` a `data/nvr/nvr.db` (uživatelé). Index záznamů lze kdykoliv obnovit
  příkazem `reindex`, protože u každé relace nahrávání leží na NAS soubor `segments.csv`.
- Přidání kamery: doplnit do `config.yaml` (+ heslo do `.env`) a `docker compose restart nvr`.
  Konfigurace go2rtc se vygeneruje sama.

## 7. Bezpečnost – doporučení

- Pokud jsou kamery v jiné lokalitě, jde RTSP internetem **nešifrovaně**. Doporučujeme VPN (např. WireGuard)
  mezi lokalitou a serverem; minimálně povolte porty kamer jen pro IP adresu serveru.
- Silná a unikátní hesla kamer, aktuální firmware, pro NVR samostatný ONVIF účet.
- Uživatelům zapnout TOTP (`--totp`).

## Vývoj a testy

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Pro vývoj bez kamer stačí v `config.yaml` použít virtuální zdroje go2rtc, například
`main_url: "ffmpeg:virtual?video=testsrc2&size=1280x720&fps=15#video=h265"`, a spustit go2rtc
a `uvicorn --factory app.main:create_app`.

Struktura:

```
app/      backend (FastAPI): recorder.py (ffmpeg + index), retention.py, onvif.py, live.py (go2rtc),
          media.py (převod/export), timeline.py, auth.py, cli.py
web/      frontend bez build kroku (ES moduly), vendor/: hls.js 1.6.15, go2rtc video-rtc.js (MIT)
tests/    pytest
```

## Licence a autor

**Autor: Uberit s.r.o.** – © 2026. FarNVR je zcela zdarma, i pro komerční použití.

Licence: **GNU AGPL-3.0** (viz [LICENSE](LICENSE) a [NOTICE](NOTICE)):

- můžete ho zdarma používat, upravovat a šířit, soukromě i komerčně,
- pokud upravenou verzi šíříte nebo ji poskytujete ostatním přes síť, musíte zveřejnit zdrojový kód
  svých úprav pod stejnou licencí,
- **povinné uvedení autora** (dodatečná podmínka podle čl. 7(b) AGPL): v rozhraní (přihlašovací stránka,
  Nastavení → O aplikaci) a v dokumentaci musí zůstat „FarNVR © Uberit s.r.o.“ s odkazem na původní projekt.

Přibalené knihovny: [hls.js](https://github.com/video-dev/hls.js) (Apache-2.0),
[go2rtc video-rtc.js](https://github.com/AlexxIT/go2rtc) (MIT).
