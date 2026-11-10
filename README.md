# Zabbix ve Grafana kurulumu

Çok site / active agent üretim kurulumu: [installation.md](../installation.md).
Yeni üretim server kurulumu için `python3 setup.py --production` kullan.

Bu rehber sunucu kurulumu ve **SSH üzerinden uzak Linux cihaz ekleme** içindir.
Komutları aksi belirtilmedikçe `staj-server` klasöründe, normal kullanıcıyla çalıştır.
Docker komutları için kullanıcının Docker erişimi olmalıdır.

## 1. Sunucuyu kur

Sunucuda çalıştır:

```sh
python3 setup.py
```

Menüden **1) Server kurulumu** seç. Port sorularında Enter varsayılanı seçer.
Paket kurulumu ve servis başlatma sorularını kontrol ederek onayla.

Kurulum şunları yapar:

- `.env` ve veritabanı parola dosyalarını oluşturur. Mevcut dosyaları korur.
- Zabbix, MySQL ve Grafana servislerini başlatır.
- Varsayılan Zabbix Admin parolasını `.env` içindeki parolayla değiştirir.
- `Essential Items` template'ini Zabbix'e import eder.

Varsayılan adresler:

| Servis | Adres / port |
| --- | --- |
| Zabbix web | `http://SUNUCU_IP:8080` |
| Grafana | `http://SUNUCU_IP:3001` |
| Zabbix server | `10081` (container içinde `10051`) |

`SUNUCU_IP` yerine kendi sunucunun IP adresini yaz. SSH ve firewall ayarlarını
kurulum değiştirmez; gerekli erişimleri ortamına göre ayrıca kontrol et.

Sihirbaz yerine elle kuracaksan aynı sıra şöyledir:

```sh
python3 scripts/prepare_config.py
docker compose config --quiet
docker compose up -d
python3 scripts/import_template.py
docker compose ps
```

Her komut başarılı olduktan sonra sonrakine geç. `import_template.py` hem Admin
parolasını hazırlar hem template'i yükler. Sihirbaz tamamlandıysa bu komutları
tekrar çalıştırman gerekmez.

## 2. Giriş bilgilerini kontrol et

`.env` dosyasını güvenli bir editörle aç. Parolaları veya token'ları paylaşma,
Git'e ekleme ve terminal çıktısına dökme.

| Değişken | Ne için kullanılır? | Ne yazılmalı? |
| --- | --- | --- |
| `ZABBIX_ADMIN_PASSWORD` | Zabbix `Admin` hesabı ve cihaz kayıt betiği | Kurulumun ürettiği parola |
| `GF_SECURITY_ADMIN_USER` | Grafana giriş kullanıcısı | Varsayılan `admin` |
| `GF_SECURITY_ADMIN_PASSWORD` | Grafana giriş parolası | Kurulumun ürettiği parola |
| `ZABBIX_GRAFANA_USER` | Grafana veri kaynağının Zabbix kullanıcısı | Varsayılan `Admin` |
| `ZABBIX_GRAFANA_PASSWORD` | Yukarıdaki Zabbix hesabının parolası | Varsayılan `${ZABBIX_ADMIN_PASSWORD}` |
| `GRAFANA_SERVICE_TOKEN` | Dashboard ve playlist oluşturma | 5. adımda Grafana'nın ürettiği token |
| `ZABBIX_SERVICE_TOKEN` | Otomasyonun Zabbix host listesini okuması | 5. adımda Zabbix'in ürettiği token |

İlk açılışta iki token alanı **boş kalabilir**. Önce servislere giriş yapıp token
üreteceksin, sonra bu alanları dolduracaksın.

Veri kaynağı parolası bir API token değildir. `ZABBIX_GRAFANA_USER=Admin` ise
`ZABBIX_GRAFANA_PASSWORD=${ZABBIX_ADMIN_PASSWORD}` bırak. Compose bu referansı
Admin parolasıyla doldurur. Ayrı bir Zabbix hesabı kullanırsan bu iki alana o
hesabın kullanıcı adını ve gerçek parolasını yaz; hesaba izlenen gruplar için
okuma izni ver.

Önemli: `.env` parolasını değiştirmek mevcut Zabbix veya Grafana hesabının
parolasını kendiliğinden değiştirmez. Zabbix bootstrap betiği yalnızca fabrika
parolası `zabbix` olan Admin hesabını günceller; başka bir parolayı sıfırlamaz.
Grafana yönetici parolası da mevcut veritabanı için `.env` üzerinden yeniden
atanmaz. Mevcut hesap parolasını arayüzden değiştirirsen ilgili `.env` kaydını da
eşleştir.

## 3. Uzak cihaza agent kur

Uzak Linux cihazda ayrı agent reposundaki kurulum sihirbazını çalıştır:

```sh
python3 setup.py
```

**2) Agent kurulumu** seç ve paket kurulumunu tamamla. TLS için mevcut PSK yolu
sorulduğunda bu aşamada TLS yapılandırmasını reddet; bir sonraki adımda sunucu
cihaza özel anahtarı üretecek ve aktaracak.

Uzak cihazda Python 3, çalışan systemd ve kurulu Zabbix agent/agent2 bulunmalı.
Sunucudan bu cihaza SSH erişimi ve cihazdaki kullanıcı için sudo yetkisi gerekli.

## 4. Uzak cihazı sunucudan kaydet

Sunucuda agent reposunun da bir kopyası bulunmalı. Bu, uzak cihaza gönderilecek
`install.py` dosyası için gereklidir.

Sunucu reposunda çalıştır:

```sh
python3 setup.py
```

**3) Sunucudan cihaz ekle** seç. Soruları şu şekilde doldur:

| Soru | Yazılacak değer |
| --- | --- |
| Cihazın Zabbix adı | Örneğin `OfisPC`; her cihaz için ayrı ad |
| Cihaz IP adresi | Uzak cihazın sunucudan erişilen IP'si |
| Sunucunun agent tarafından görülen IP adresi | Uzak cihazın bağlantıda gördüğü sunucu kaynak IP'si |
| SSH hedefi | Örneğin `kullanici@192.168.1.50` |
| Agent repo yolu | Sunucudaki agent reposunun tam yolu |

NAT veya VPN varsa kaynak IP, sunucunun bildiğin LAN IP'sinden farklı olabilir.
Bu adres agent'ın `Server=` izin listesine eklenir.

Gösterilen planı kontrol et ve kayıt işlemini onayla. İşlem agent ayarlarını
yedekler ve agent servisini yeniden başlatır. Her cihaz için ayrı PSK üretilir:

- Sunucudaki anahtar: `zabbix/tls/private/CIHAZ_ADI.psk`
- Uzak cihazdaki anahtar: `/etc/zabbix/tls/staj-CIHAZ_ADI.psk`

PSK'yi elle üretmen veya ilk cihazın anahtarını başka cihazda kullanman gerekmez.
Sunucunun `.env` dosyası ve API token'ları uzak cihaza gönderilmez.

Başarılı kurulum sonunda **`4/4 Complete: PSK succeeds; plaintext rejected`**
mesajını görmelisin. Zabbix hostu `Linux servers` grubuna alınır, `Essential
Items` bağlanır ve PSK zorunlu yapılır. İşlem hata verirse tamamlanmış sayma;
hatayı giderip aynı cihaz adıyla tekrar çalıştır. Mevcut anahtar korunur.

Zabbix'te hostun kullanılabilirliğini ve Encryption ayarını kontrol et.
`No` görünüyorsa PSK kaydı tamamlanmamıştır. Ayrıntılı komutlar ve geri alma:
[TLS kayıt rehberi](zabbix/tls/README.md).

## 5. Grafana ve Zabbix token'larını oluştur

Token'ı kendin rastgele yazma. İlgili uygulamanın ürettiği **gizli değeri**
kopyala; token'ın adı veya açıklaması kimlik doğrulamak için kullanılmaz.

### Grafana token'ı

1. Grafana'ya yönetici hesabıyla giriş yap.
2. **Administration → Users and access → Service accounts** bölümünü aç.
3. `host-dashboard-sync` adında **Editor** rolünde servis hesabı oluştur.
4. Hesabın içinde **Add service account token** ile token üret.
5. Üretilen değeri `.env` içindeki `GRAFANA_SERVICE_TOKEN=` alanına yapıştır.

### Zabbix token'ı

1. Zabbix'te otomasyon için bir kullanıcı oluştur veya uygun hesabı kullan.
2. Kullanıcının grubuna `Linux servers` host grubu için **Read** izni ver.
3. Kullanıcı rolünde API erişimi açık olmalı; `hostgroup.get` ve `host.get`
   metotlarına izin verilmeli.
4. Yönetici hesabıyla **Users → API tokens → Create API token** bölümünü aç.
5. İlgili kullanıcıyı seç, token'ı oluştur ve **Generate** ile gizli değeri al.
6. Bu değeri `.env` içindeki `ZABBIX_SERVICE_TOKEN=` alanına yapıştır.

Token süresi belirlediysen süresi dolmadan yenile. İki token farklıdır;
Grafana token'ını Zabbix alanına veya veri kaynağı parola alanına yazma.

## 6. Grafana veri kaynağını test et

Grafana'da **Connections → Data sources → Zabbix** aç. Veri kaynağı kurulumda
otomatik oluşturulur; UID'si `zabbix` olur. **Save & test** ile bağlantıyı test et.

Kullanıcı/parola hatası çıkarsa 2. adımdaki `ZABBIX_GRAFANA_USER` ve
`ZABBIX_GRAFANA_PASSWORD` alanlarını kontrol et. Hesap geçici kilitlendiyse
ardışık giriş denemelerini durdur ve kilidin kalkmasını bekle.

`.env` içindeki veri kaynağı bilgilerini sonradan değiştirdiysen Grafana'ya
uygulamak için aşağıdaki komutları çalıştır. Bu işlem Grafana container'ını
gerekirse yeniden oluşturur; kısa süreli erişim kesintisi olabilir:

```sh
docker compose config --quiet
docker compose up -d --no-deps grafana
```

Yalnızca `docker compose restart` yeni `.env` değerlerini aktarmaya yetmez.

## 7. Cihaz dashboard'larını ve playlist'i başlat

İki token `.env` içine yazıldıktan sonra çalıştır:

```sh
docker compose --profile host-sync config --quiet
docker compose --profile host-sync up -d --no-deps host-dashboard-sync
docker compose logs --tail 30 host-dashboard-sync
```

Bu komut yalnızca dashboard otomasyonunu başlatır; Zabbix, MySQL ve Grafana'yı
yeniden başlatmaz. Başarılı döngüde logda `Synced ... hosts` görürsün.

Otomasyon varsayılan olarak 60 saniyede bir `Linux servers` grubundaki etkin
hostları kontrol eder. Grafana sayfasını yenile:

- **Dashboards → Zabbix Linux devices:** Her cihazın dashboard'u.
- **Dashboards → Playlists → Zabbix — Linux devices:** Cihazları sırayla gösteren playlist.

Playlist'i arayüzden başlat; varsayılan geçiş süresi 30 saniyedir. Grupta etkin
host yoksa cihaz dashboard'u oluşmaz. Sonradan eklenen cihazlar sonraki döngüde
alınır; açık playlist'e yansımazsa playlist'i yeniden başlat.

Normal `docker compose up -d`, `host-sync` profilini ilk kez etkinleştirmez;
yukarıdaki başlatma adımı gereklidir.

## 8. Sonraki `.env` değişikliklerini uygula

Veri kaynağı bilgilerini veya token'ları değiştirdiğinde:

```sh
docker compose --profile host-sync config --quiet
docker compose --profile host-sync up -d --no-deps grafana host-dashboard-sync
docker compose logs --since 2m --tail 30 host-dashboard-sync
```

Compose değişen ortam değerlerini container'lara aktarır. Grafana yeniden
oluşturulursa kısa süreli erişim kesintisi olur. Zabbix ve MySQL etkilenmez.

## Sorun kontrolü ve geri alma

| Belirti | Kontrol |
| --- | --- |
| Dashboard/playlist yok | `host-dashboard-sync` çalışıyor mu; token yetkileri ve `Linux servers` üyeliği doğru mu? |
| `latin-1` / Türkçe karakter hatası | Token adı yerine uygulamanın ürettiği gerçek token değeri yazılmış mı? |
| Data source kullanıcı/parola hatası | Zabbix hesabının gerçek parolası girilmiş mi; hesap kilitli mi? |
| Agent `access permissions` hatası | Agent logundaki gerçek kaynak IP, `Server=` listesinde izinli mi? |
| Gauge grafiği bozuk | Grafana adresinde Dark Reader gibi görünümü değiştiren uzantıları kapat. |

Dashboard otomasyonunu geri almak/durdurmak için:

```sh
docker compose stop host-dashboard-sync
```

Oluşturulmuş dashboard ve playlist'ler korunur. `.env` değişikliğini geri almak
için eski değerleri güvenli kaydından geri yazıp 8. adımdaki uygulama komutunu
çalıştır. Agent değişikliğini geri almak için kurulum çıktısındaki config yedeği
ve [TLS geri alma adımlarını](zabbix/tls/README.md) kullan.

Tüm proje servislerini verileri koruyarak durdurmak için:

```sh
docker compose --profile host-sync stop
```

`.env`, `env_vars/` parola dosyaları ve `zabbix/tls/private/` kayıtlarını güvenli
yedekle. MySQL verileri `zbx_env/var/lib/mysql/`, Grafana verileri Docker'ın
`grafana-storage` volume'ündedir. Volume veya veri dizinlerini silme; `down -v`
çalıştırma.

Dashboard kaynak tasarımı: `grafana/templates/linux-template.json`.
Otomasyon ayrıntıları: [host-sync rehberi](grafana/host-sync/README.md).
Zabbix Docker tanımları upstream `zabbix/zabbix-docker` projesinden alınmıştır;
lisans: [LICENSE](LICENSE).
