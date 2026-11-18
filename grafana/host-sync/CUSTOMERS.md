# Müşteri bazlı izleme pilotu

Bu mod müşteri → cihaz gezinmesi ve canlı Zabbix sorguları oluşturur. Zabbix
hostlarını, proxy atamalarını, firewall kurallarını veya servisleri değiştirmez.
Mevcut playlist ve cihaz dashboard'ları silinmez. Müşteri modu açıkken eski
playlist senkronizasyonu durur; önceki nesneler saklanır.

## Kapsam

- Tek genel görünüm: `Customers — overview`.
- Firma başına cihaz listesi, aktif sorunlar ve proxy bağlantı yaşı.
- Cihaz başına agent verisi yaşı ve ortak `Device details` dashboard'una bağlantı.
- Ortak cihaz ekranında OS bilgisi, kullanılan RAM, CPU kullanımı, ağ, uptime,
  sürücü bazında doluluk ve boş alan.
- Seçili Windows servisleri/process'ler ve web senaryoları için ortak kontrol ekranı.
- Resmi Dell/HPE template'leriyle iDRAC/iLO için ayrı donanım ekranı; üretici
  durum kodları tek bir varsayımla yeşil/kırmızıya çevrilmez.
- Bilinmeyen/veri gelmeyen durum `UNKNOWN`; sıfır sorun sayısı tek başına sağlıklı
  anlamına gelmez. Veri yaşı 180 saniyede turuncu, 300 saniyede kırmızı olur.
- Geçici müşteri kimlikleri `musteri01`…`musteri10`, görünen adlar `Firma 01`…`Firma 10`.
- Coğrafi koordinatlar henüz yok; harita, tam ESXi/Hyper-V envanteri, Veeam iş
  sonuçları ve AD replikasyon kontrolleri sonraki aşamalardır. Telegram çalışması
  ertelenmiştir; bu değişiklik bildirim göndermez veya action oluşturmaz.

Grafana durumları canlı veri kaynağı sorgularıyla yeniler. JSON'a durum anlık
kopyaları gömülmez; senkronizasyon döngüsü yalnızca yapı/cihaz listesi değişince
dashboard yazar. Yeni cihaz listesinin görünmesi için açık dashboard'u yenile.

## 1. Bir müşteriyi hazırla

Önce `Firma 01` ile pilot yap. Zabbix'te:

1. `Customers/musteri01` host grubunu oluştur.
2. İlgili cihazları bu gruba ekle; diğer OS gruplarında da kalabilirler.
   Bir cihaz yalnızca bir etkin müşteri grubuna ait olmalı. Aynı müşteri içinde
   cihazların görünen adları benzersiz olmalı; firmalar arasında aynı ad olabilir.
3. Cihazların **Monitored by** ayarını ilgili proxy ile eşleştir. Bu otomasyon
   proxy ataması yapmaz veya atamanın doğruluğunu doğrulamaz.
4. Proxy'nin teknik adını öğren; örnekte `proxy-musteri01`. Gerçekte farklıysa
   dosyada ve heartbeat host macros alanında gerçek adı kullan.
5. Senkronizasyon API kullanıcısına müşteri grubu için Read yetkisi ve mevcut
   `hostgroup.get` / `host.get` izinlerini ver.

Grafana veri kaynağının kullandığı Zabbix hesabı da müşteri grubunu ve
`Monitoring/Proxies` grubunu okuyabilmeli. Grafana'nın `Save & test` kontrolünün
geçmesi, tüm host/grup izinlerinin bulunduğu anlamına gelmez.

## 2. Disk keşfi ve veri yaşı

Uygun güncel Linux/Windows aktif/pasif template'ini Zabbix arayüzünden import
et. **Delete missing kapalı** olsun. Mevcut teknik adlar ve UUID'ler korunur.
Varsayılan Linux CLI importu da güncel disk keşfini içerir.

- `vfs.fs.discovery` her dosya sistemi için doluluk (%), boş alan (B) ve toplam
  boyut (B) oluşturur. Keşif periyodu bir saat, ölçüm periyodu bir dakikadır;
  ilk denemede keşif için Execute now kullanılabilir.
- `{$VFS.FS.FSNAME.MATCHES}`, `{$VFS.FS.FSNAME.NOT_MATCHES}` ve FSTYPE karşılıkları
  keşif kapsamını belirler. Linux'ta geçici/sanal dosya sistemleri filtrelenir;
  Windows'ta NTFS/ReFS/FAT ailesi varsayılan olarak kapsanır.
- `{$DISK.USED.HIGH}` ve `{$DISK.USED.RECOVERY}` varsayılanları korunur. Bir sürücü
  için `{$DISK.USED.HIGH:"D:"}` veya `{$DISK.USED.HIGH:"/data"}` gibi context macro
  tanımlanabilir; tanımlanmayan sürücüler genel eşiği kullanır.
- Eski `Disk Usage` item'ı ve tek sürücü trigger'ı geçmişleri korunarak devre dışı
  bırakılır. Yeni keşif veri üretene kadar disk izlemesinde boşluk olabilir;
  önce pilotta doğrula, tüm müşterilere aynı anda import etme.
- `Agent data age`, `now()-lastclock(//system.uptime)` ile uptime örneğinin
  zaman damgasını esas alır. Hiç örnek yoksa desteklenmeyen/verisiz kalır; sıfır
  üretilmez. Bu bir ağ erişilebilirlik testi değildir. Proxy gecikmesi/buffer ve
  bakım sırasında veri yaşının yükselmesi ayrıca değerlendirilmelidir.
- Geniş process master item'ı ve discovery kuralı varsayılan olarak devre dışı
  bırakılır; geçmiş silinmez. Kritik process/servisler açık listelerle seçilir.
  İsteğe bağlı profiller ve rol örnekleri için [profil rehberine](../../zabbix/templates/PROFILES.md) bak.

## 3. Proxy heartbeat

`zabbix/templates/customer-proxy-health.yaml` dosyasını import et. Sonra:

1. `Monitoring/Proxies` grubunda `proxy-health-musteri01` teknik ve görünen adıyla
   bir host oluştur; **Monitored by: Server** seç, **Enabled** bırak.
2. `Customer proxy health` template'ini bağla. Agent interface gerekmez.
3. `{$PROXY.NAME}` macro'sunu gerçek proxy adıyla eşleştir.

`Proxy last access` server tarafındaki internal item'dır. `Proxy heartbeat age`
server saatinden son bağlantı zamanını çıkarır. Üç dakika bağlantı gelmezse
High, beş dakika izleme verisi yoksa Warning trigger'ı oluşur. Negatif yaş,
saat tutarsızlığı ihtimaliyle kırmızı gösterilir. Proxy'nin güncel olması
cihazlarının tamamının güncel olduğu anlamına gelmez.

Bu template müşteri cihaz gruplarından ayrı tutulur; cihaz sayısını artırmaz.
Telegram için mevcut `notify=telegram` action'ı kullanılabilir; bot/grup ayarları
gerekir. Proxy kesintisinde cihaz alarm bağımlılıkları otomatik kurulmaz;
bildirimleri yaygınlaştırmadan önce pilotta bağımlılık ve bakım davranışı ayarlanmalı.

## 4. Yapılandırma

Sunucuda `zabbix-server` dizininde örnek dosyayı yerel yapılandırmaya kopyala;
mevcut dosyanın üzerine yazma:

```sh
cp -n grafana/host-sync/customers.example.json grafana/host-sync/customers.json
```

Örnekte yalnızca `musteri01` etkin. Dosyayı düzenleyerek gerçek grup/proxy
adlarını eşleştir. Diğer müşterileri grupları ve proxy heartbeat hostları hazır
olduğunda `enabled: true` yap. Yerel dosya Git dışında tutulur; gizli değer
ve parola içermez. Her etkin müşterinin grubuna erişilebilmelidir; eksik grupta
otomasyon mevcut dashboard'ları değiştirmeden hata verir. Boş ama mevcut grup,
cihazsız ve sağlık durumu belirsiz olarak gösterilir.

`env_vars/.env_dashboard_sync` içine ekle:

```dotenv
CUSTOMER_CONFIG=/app/customers.json
```

Bu modda `ZABBIX_HOST_GROUPS` yerine müşteri dosyasındaki gruplar kullanılır.
Müşteri modu için yeni Python paketi veya Grafana eklentisi gerekmez; kurulu
Zabbix veri kaynağı ve Grafana table/stat/gauge/text panelleri kullanılır.

## 5. Uygulama ve kontrol

Kaynak değişikliklerini aldıktan, token/grup/template ayarlarını tamamladıktan
sonra yalnızca otomasyonu yeniden oluştur:

```sh
docker compose --profile host-sync config --quiet
docker compose --profile host-sync up -d --no-deps --force-recreate host-dashboard-sync
docker compose logs --since 2m --tail 30 host-dashboard-sync
```

Compose mount'ları artık tek dosya yerine dizindir; Git güncellemesinde eski
JSON dosyasının container içinde kalması önlenir. Bu ilk mount değişikliği için
container yeniden oluşturma gerekir. Grafana/Zabbix/MySQL yeniden başlatılmaz.

Grafana → **Dashboards → Zabbix Customers** altında:

1. `Customers — overview` içinde firma kartını aç.
2. Firmanın cihazını seç; OS ve veri yaşını kontrol et.
3. Cihazda kullanılan RAM ve her sürücünün ayrı doluluğunu doğrula.
   Service and website checks bağlantısı müşteri/cihaz seçimini koruyarak isteğe
   bağlı profil kontrollerini açar.
   Resmi Dell iDRAC/HP iLO template'li hostlar listeden donanım ekranına; Website
   availability template'li hostlar kontrol ekranına yönlenir. Bunlarda agent
   uptime yaşı beklenmez. Donanım sensörleri değişmeyen değerleri saatlerce
   saklayabileceği için ekranda 24 saatlik son bilinen değerler ile ayrı beş
   dakikalık SNMP availability kontrolü kullanılır. Fiziksel sunucu sayısı ile
   Zabbix izleme kaydı sayısı aynı değildir.
4. Proxy monitörü hazır değilse `UNKNOWN` görülmeli; sağlıklı varsayılmamalı.
5. Ağ/servis kesintilerini üretim üzerinde deneme; kesinti ve geri kazanım
   kontrollerini ayrı pilot cihazlarda yap.

Yerel testler:

```sh
python3 -B -m unittest discover -s grafana/host-sync -p 'test_*.py'
python3 -B -m unittest discover -s scripts -p test_import_template.py
```

Canlı Grafana/Zabbix API importu, LLD ve gerçek proxy kesintisi yerel testlerle
kanıtlanmış değildir; sunucudaki pilotta doğrulanmalıdır.

## Geri alma

- Müşteri modunu kapatmak için `CUSTOMER_CONFIG` satırını kaldır; Compose config
  doğrulamasından sonra yalnızca otomasyonu yeniden oluştur. Eski playlist
  senkronizasyonu devam eder; müşteri dashboard'ları silinmez.
- Disk keşfini geri almak için yeni filesystem discovery kuralını/üretilen
  item'ları ve trigger'larını devre dışı bırak. Eski `Disk Usage` item'ını ve
  eski disk trigger'ını tekrar etkinleştir. Geçmiş verileri silme.
- Eski dashboard sorgusuna dönmek için kaynak JSON yedeğini geri koy. Yeni
  sürücü keşfi devrede kalacaksa eski tek-disk paneline geçme.
- Proxy heartbeat template'ini kaldırmak yerine hostu devre dışı bırak;
  geçmişi koru. Volume veya veritabanı silme.

Kaynaklar:
[Grafana Zabbix sorguları](https://grafana.com/docs/plugins/alexanderzobnin-zabbix-app/latest/query-editor/),
[Zabbix lastclock](https://www.zabbix.com/documentation/7.4/en/manual/appendix/functions/history#lastclock),
[Proxy internal item](https://www.zabbix.com/documentation/7.4/en/manual/config/items/itemtypes/internal).
