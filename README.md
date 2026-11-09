# Staj Server — Zabbix ve Grafana

Zabbix 7.4, MySQL ve Grafana servisleri; Linux template'leri, dashboard'lar,
playlist senkronizasyonu ve sunucu tarafından host kaydı. Bu klasör ayrı bir
Git reposuna alınabilecek bağımsız sunucu kaynak paketidir.

**Bu kaynak kopyası başlatılmadı.** Şu an çalışan kurulum `staj-izleme`
klasöründedir ve bu düzenlemede değiştirilmedi. Canlı `.env`, token, PSK,
veritabanı ve Grafana volume verileri bu klasöre kopyalanmadı.

## Klasörler

| Konum | İçerik |
| --- | --- |
| `compose.yaml`, `compose/` | Zabbix, Grafana, MySQL ve host-sync servisleri |
| `.env.example`, `env_vars/` | Yeni kurulum ayarları ve servis yapılandırmaları |
| `scripts/prepare_config.py` | Yerel `.env` ve veritabanı parolalarını hazırlar |
| `zabbix/templates/` | Essential Items Linux template'i |
| `zabbix/tls/enroll.py` | SSH üzerinden agent hazırlama ve Zabbix host kaydı |
| `zabbix/tls/private/` | Çalıştırılınca oluşan, Git'e alınmayan PSK ve işlem kayıtları |
| `grafana/templates/` | Cihaz dashboard kaynak tasarımı |
| `grafana/dashboards/`, `grafana/provisioning/` | Genel dashboard ve veri kaynağı provisioning |
| `grafana/host-sync/` | Cihaz dashboard'ları ve playlist otomasyonu |
| `docs/kurulum.md` | Yeni sunucu kurulum adımları |

## Sunucuyu hazırlama

Docker Compose ve Python 3 gerekir. Yeni kurulum için:

```sh
python3 scripts/prepare_config.py
docker compose config --quiet
```

[Kurulum yönergesini](docs/kurulum.md) tamamladıktan sonra servisleri başlat.
Compose proje adı `staj-server`dir. Varsayılan web portları Zabbix `8080`,
Grafana `3001`; yayınlanan Zabbix server portu `10081`dir. Bu portlar ve Docker
alt ağları mevcut `staj-izleme` kurulumuyla çakışabilir; aynı makinede paralel
başlatmadan önce portları ve alt ağları ayır veya planlı geçiş yap.

| Hesap | Kullanıcı | Yerel parola / token kaydı |
| --- | --- | --- |
| Zabbix yönetimi | `Admin` | `.env`: `ZABBIX_ADMIN_PASSWORD` |
| Grafana yönetimi | `admin` | `.env`: `GF_SECURITY_ADMIN_PASSWORD` |
| Grafana veri kaynağı | `ZABBIX_GRAFANA_USER` ile belirlenir | `.env`: `ZABBIX_GRAFANA_PASSWORD` |
| Grafana servis hesabı | Oluşturulacak Editor hesabı | `.env`: `GRAFANA_SERVICE_TOKEN` |
| Zabbix salt okunur API erişimi | Oluşturulacak entegrasyon hesabı | `.env`: `ZABBIX_SERVICE_TOKEN` |

Gerçek değerler README'ye veya Git'e yazılmaz. `prepare_config.py` Zabbix
hesaplarını/API token'larını oluşturmaz; arayüzde ayarlanan değerler `.env`
dosyasına kaydedilmelidir. Yeni kaynak repo eski ortamın hesaplarını içermez.

## Ayrı agent reposuyla host kaydı

Agent reposunu istediğin yere klonla. Bu repo agent kurulum kodunu içermez;
`--agent-source` ile bağımsız agent reposunun yerel yolunu alır:

```sh
python3 zabbix/tls/enroll.py --host YeniPC --address 172.16.53.150 --ssh kullanici@172.16.53.150 --server 172.16.53.132 --agent-source /tam/yol/agent-reposu
```

IP'leri ve kullanıcıyı ortama göre değiştir. Klasörler bu çalışma alanındaki
gibi `staj-server` ve `staj-agent` adıyla yan yanaysa `--agent-source` verilmeden
de çalışır. Farklı repo adları veya konumlar için parametreyi açıkça belirt.
Önizleme için `--plan` ekle.

Sunucu PSK üretir ve Zabbix API'sini yönetir. Hedef cihaza **yalnızca** agent
reposundaki `install.py` ile o cihaza ait PSK gönderilir. Sunucu `.env` dosyası,
Admin parolası ve API token'ları hedefe gönderilmez. Agent scripti de Zabbix
API'sine erişmez. Hedefte agent/agent2 ve Python 3 kurulu olmalıdır; gerekli
agent işlemlerinde interaktif sudo istenir.

[TLS akışı, parametreler ve geri alma](zabbix/tls/README.md).

## Dashboard ve playlist

Host-sync `Linux servers` grubundaki etkin cihazları 60 saniyede bir kontrol
eder. `Zabbix Linux devices` klasörüne cihaz dashboard'larını oluşturur ve
`Zabbix — Linux devices` playlist'ine ekler. Geçiş süresi 30 saniyedir.
Tasarımları `grafana/templates/linux-template.json` üzerinden düzenle.

```sh
docker compose --profile host-sync up -d
docker compose --profile host-sync ps
docker compose logs --tail 30 host-dashboard-sync
docker compose --profile host-sync stop
```

`stop` verileri silmez. MySQL verileri `zbx_env/var/lib/mysql/` altında,
Grafana verileri `staj-server_grafana-storage` volume'ünde tutulur. `.env`,
veritabanı parola dosyaları ve `zabbix/tls/private/` kayıtlarını yedekle;
`down -v` veya veri dizini temizleme işlemleri yapma.

## Testler

Agent reposu klonlu olmasa da sunucu testleri bağımsız çalışır:

```sh
python3 -B -m unittest discover -s zabbix/tls -p 'test_*.py'
python3 -B -m unittest discover -s grafana/host-sync -p 'test_*.py'
docker compose --env-file .env.example --profile host-sync config --quiet
```

Zabbix Docker tanımları upstream `zabbix/zabbix-docker` projesinden alınmıştır;
lisans [LICENSE](LICENSE) dosyasındadır.
