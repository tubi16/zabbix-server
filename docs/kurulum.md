# Kurulum ve kullanım

Bu belge ayrı sunucu reposunun yeni kurulumu içindir. Bu kaynak kopyası
başlatılmadı; çalışma alanındaki mevcut `staj-izleme` kurulumu değişmedi.
Agent kurulum scripti bu repo içinde değildir; ayrı agent reposu gerekir.

## 1. Yerel ayarları hazırla

Proje klasöründe `python3 scripts/prepare_config.py` çalıştır. Bu işlem `.env`
ve veritabanı parola dosyalarını yeni değerlerle oluşturur; mevcut dosyaları
değiştirmez. API token'ları kopyalanmaz veya otomatik üretilmez.

`.env` dosyasındaki `GF_SECURITY_ADMIN_PASSWORD` yeni Grafana yönetici parolasıdır.
Zabbix Admin parolası ilk kurulumda otomatik hazırlanmışsa `.env` içindeki
`ZABBIX_ADMIN_PASSWORD` alanında tutulur. Parolaları ve token'ları paylaşma. Grafana veri kaynağı için
`ZABBIX_GRAFANA_USER` ve `ZABBIX_GRAFANA_PASSWORD` değişkenlerini Zabbix hesabına
göre doldur. Bu hesabın izlenecek gruplara okuma izni olmalıdır.

Yeni kurulumda `prepare_config.py`, `.env` için rastgele Admin parolası üretir.
Mevcut `.env` korunur; `ZABBIX_ADMIN_PASSWORD` boşsa önce güçlü bir parola yaz.
Servisler başladıktan sonra `python3 scripts/bootstrap_admin.py` çalıştır.
Sihirbaz bunu otomatik yapar. Betik API'yi bekler, `.env` parolasını doğrular;
gerekirse yalnızca varsayılan `Admin / zabbix` parolasını `.env` değeriyle değiştirir.
Başka bir mevcut parola zorla sıfırlanmaz. Parolalar çıktıya yazılmaz.
API adresi mevcut otomasyonla aynı şekilde `http://127.0.0.1:8080`'dir.
Bu işlem için servis yeniden başlatmak gerekmez. Parolayı daha sonra arayüzden
tekrar değiştirirsen `.env` kaydını da güncelle; geri dönüşte varsayılan parolayı kullanma.

Compose proje adı `staj-server`dir. Varsayılan portlar Zabbix web 8080/8443,
Grafana 3001 ve Zabbix server 10081 olarak ayrılmıştır. Ağlar da mevcut
kurulumdan farklı alt ağlar kullanır. Makinedeki diğer servislerle çakışma
varsa `.env` dosyasında port ve alt ağları değiştir.

## 2. Ana servisleri başlat

```sh
docker compose config --quiet
docker compose up -d
python3 scripts/import_template.py
docker compose ps
```

`http://localhost:8080` üzerinden Zabbix'i, `http://localhost:3001` üzerinden
Grafana'yı aç. Yeni veritabanı oluşturulur; mevcut hostlar ve geçmiş metrikler
bu kaynak kopyasına aktarılmamıştır. Zabbix hesabını hazırladıktan sonra
`.env` içindeki veri kaynağı kimlik bilgilerini doldur ve `docker compose up -d
--no-deps grafana` ile yalnızca bu kopyadaki Grafana'ya uygula.

## 3. Template ve dashboard

`scripts/import_template.py` önce Admin parolasını hazırlar, ardından
`zabbix/templates/essential-items.yaml` dosyasını API ile import eder ve doğrular.
Sihirbaz aynı adımı otomatik çalıştırır. Mevcut öğeler güncellenir, eksikler
oluşturulur; silme yapılmaz. Template'i Linux hostlarına bağla.
Dinamik ağ arayüzü için [Zabbix açıklamasına](../zabbix/README.md)
bak. Template pasif agent erişimi kullanır; yeni kurulumun server'ının hosttaki
agent tarafından kabul edilmesi gerekir. Kaynak kurulumdaki agent ayarlarını
değiştirmek bu kopyalama işleminin parçası değildir.

Agent'ın TLS kurulumu ayrı agent reposundadır. Sunucudan yeni cihazı tek
komutla kaydetmek için [host kayıt otomasyonunu](../zabbix/tls/README.md) kullan;
`--agent-source` ile klonladığın agent repo yolunu belirt.

Grafana genel dashboard'u provisioning ile yükler. Cihaz tasarımını elle
denemek için `grafana/templates/linux-template.json` dosyasını import et.
Tüm veri kaynağı referansları bu kurulumdaki `zabbix` UID'sini kullanır.

## 4. Otomatik cihaz dashboard'ları ve playlist

Grafana'da Editor rolünde servis hesabı token'ı; Zabbix'te `Linux servers`
grubunu okuyabilen, `hostgroup.get` ve `host.get` izinli API token'ı oluştur.
Bu iki token'ı `.env` dosyasındaki `GRAFANA_SERVICE_TOKEN` ve
`ZABBIX_SERVICE_TOKEN` alanlarına yaz. Zabbix veri kaynağının da aynı
hostları okuyabilmesi gerekir.

Grup adı ve süreleri değiştirmek istersen `env_vars/.env_dashboard_sync.example`
dosyasını `env_vars/.env_dashboard_sync` olarak kopyala ve düzenle.
Varsayılanlar: `Linux servers`, 60 saniyelik senkronizasyon, 30 saniyelik geçiş.

```sh
docker compose --profile host-sync up -d --no-deps host-dashboard-sync
docker compose logs --tail 30 host-dashboard-sync
```

`Zabbix Linux devices` klasöründe cihaz dashboard'ları oluşturulur. Grafana'da
`Zabbix — Linux devices` playlist'ini başlat. Yeni etkin hostlar otomatik eklenir;
listeden çıkan hostların dashboard'ları silinmez. Oluşturulan dashboard'larda
değişiklik yapmak yerine kaynak template'i düzenle. Ayrıntılar:
[otomasyon yönergesi](../grafana/host-sync/README.md).

## 5. Kontrol ve durdurma

```sh
python3 -B -m unittest discover -s grafana/host-sync -p 'test_*.py'
docker compose config --quiet
docker compose stop host-dashboard-sync
docker compose stop
```

Son iki komut sırasıyla otomasyonu ve bu proje kopyasının servislerini durdurur.
Veritabanı dizinlerini veya Docker volume'lerini silme. Bu komutlar yalnızca
`staj-server` Compose projesine uygulanır. Mevcut `staj-izleme` kurulumu ayrı
projede çalışır; yeni kaynak paketinin hazırlanması onu durdurmaz veya taşımaz.
