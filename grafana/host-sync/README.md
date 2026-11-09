# Host dashboard ve playlist otomasyonu

Grafana 13 (dashboard.grafana.app/v2) ve Zabbix 7.4 API kullanılır.
Ek Python paketi gerektirmez. `host-dashboard-sync` Compose servisi 60 saniyede
bir `Linux servers` grubundaki etkin hostları okur; her host için export edilmiş
Linux dashboard'undan ayrı dashboard üretir. `Zabbix — Linux devices` playlist'i
30 saniyelik geçişle bunları gösterir. Dashboard'lar `Zabbix Linux devices`
klasöründe oluşturulur; kök dizin yetki farklılıklarından etkilenmez. Playlist'i Grafana arayüzünden bir kez
başlatmak gerekir; servis tarayıcı açmaz.

## Token oluşturma

Alternatif olarak `.env` dosyasına `GRAFANA_SERVICE_TOKEN` ve
`ZABBIX_SERVICE_TOKEN` değişkenlerini ekleyebilirsin. Compose bunları yalnızca
otomasyon servisine aktarır; doluysa token dosyalarına göre önceliklidir.
Bu dosya Git tarafından yok sayılır. Ortam değişkenini değiştirdikten sonra
yalnızca otomasyon servisini `up -d --no-deps host-dashboard-sync` ile yeniden
oluştur. Token içeren `docker compose config` veya `docker inspect` çıktısını
paylaşma; doğrulama için `config --quiet` kullan.

1. Grafana'da **Administration → Users and access → Service accounts** bölümünde
   `host-dashboard-sync` hesabını **Editor** rolüyle oluştur. Hesabın içinde
   **Add service account token** seç; token'ı oluştur ve kopyala. Kurumda özel
   RBAC varsa dashboard/playlist oluşturma ve güncelleme ile veri kaynağı okuma
   yetkilerini ver. Mevcut kök dashboard'larının klasöre taşınması gerekiyorsa
   geçici Admin gerekebilir; taşıma sonrasında Editor'a geri dön.
   İzleme verilerine erişim ise dashboard'un Zabbix veri
   kaynağı hesabının izinlerine bağlıdır.
2. Zabbix'te API kullanıcısına `Linux servers` host grubu için **Read** yetkisi
   ver. Kullanıcı rolünde API erişimi ile `hostgroup.get` ve `host.get` izinleri
   açık olsun. **Users → API tokens → Create API token** bölümünde bu kullanıcı
   için token oluştur; **Generate** ile üretilen değeri kopyala. Host/template
   değiştirme izni gerekmez. Bir süre sonu belirlersen yenileme tarihini takip et.
3. Aşağıdaki komutu yerel terminalde çalıştır ve istenen token'ları yapıştır.
   Giriş ekranda görünmez, shell geçmişine veya Git'e yazılmaz:

   ```sh
   cd /home/tubi/Projects/staj/staj-server
   python3 grafana/host-sync/setup_tokens.py
   ```

   Token'lar `grafana/host-sync/secrets/grafana_token` ve `zabbix_token`
   dosyalarına 0600 izinleriyle yazılır. Mevcut token dosyaları korunur.
   Token'ları sohbete gönderme.

Resmi kaynaklar: [Grafana servis hesapları](https://grafana.com/docs/grafana/latest/administration/service-accounts/),
[Zabbix API kimlik doğrulaması](https://www.zabbix.com/documentation/7.4/en/manual/api),
[Grafana playlist API](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/playlist/).

## Yapılandırma ve başlatma

Gerekirse `env_vars/.env_dashboard_sync.example` dosyasını
`env_vars/.env_dashboard_sync` olarak kopyala ve değerleri değiştir. Varsayılan
veri kaynağı UID'si çalışan export'taki `zabbix` değeridir. Farklı bir
Grafana'da veri kaynağı UID'sini güncelle. API'lerin aynı Zabbix ortamını işaret
ettiğinden emin ol. Harici adresler için `ZABBIX_URL` ve `GRAFANA_URL` de
tanımlanabilir; token'ları harici ortamlarda HTTPS üzerinden kullan.

```sh
docker compose -f compose.yaml --profile host-sync config --quiet
docker compose -f compose.yaml --profile host-sync up -d --no-deps host-dashboard-sync
docker compose -f compose.yaml logs --tail 30 host-dashboard-sync
```

İkinci komut yalnızca yeni otomasyon servisini başlatır; Grafana/Zabbix/MySQL'i
yeniden başlatmaz. Mevcut servisler çalışıyor olmalıdır. Python container imajı
yerelde yoksa Docker indirir. İlk kurulumdan sonra `unless-stopped` politikası
otomasyonu yeniden açılışlarda çalıştırır. Tam kurulumda profili etkinleştirmek
için Compose komutlarına `--profile host-sync` ekle.

Grafana **Dashboards** listesinde `zabbix-host-sync` etiketini; **Playlists**
listesinde `Zabbix — Linux devices` playlist'ini bulup başlat. Host adı, grup
ve template değişiklikleri sonraki senkronizasyonda uygulanır. Oluşturulan
dashboard'lar için kaynak JSON'u düzenle; üretilen kopyalarda yapılan manuel
değişiklikler sonraki kaynak güncellemesinde üzerine yazılır. Kimlikler host ID
üzerinden sabittir. Aynı kimlikte otomasyona ait olmayan nesneler ezilmez.

Devre dışı bırakılan, silinen veya gruptan çıkarılan hostlar playlist'ten çıkar;
dashboard'ları geçmiş/referans için korunur. Host grubu bulunamazsa playlist
korunur. Grupta hiç etkin host kalmazsa playlist boşaltılır. API hatasında döngü
bir dakika sonra yeniden dener; token veya API yanıt gövdeleri loglanmaz.
Oynayan playlist'e yeni eklenen cihazlar görünmezse playlist'i yeniden başlat.

## Kontrol ve geri alma

```sh
python3 -B -m unittest discover -s grafana/host-sync -p 'test_*.py'
docker compose -f compose.yaml stop host-dashboard-sync
```

Geri alma için yalnızca otomasyon servisini durdur. Dashboard ve playlist
silinmez; diğer servisler etkilenmez. Tekrar başlatmak için yukarıdaki `up`
komutunu kullan. Token yenilemede ilgili dosyayı güvenli bir editörde güncelle;
servis token'ları her döngüde yeniden okur.
