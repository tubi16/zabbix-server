# Temel ve seçilen rol kontrolleri

Bu dosyalar Zabbix 7.4 içindir. Telegram ayarları bu aşamanın kapsamı dışında;
şablonlar mesaj göndermez, yalnızca item/trigger tanımlar. Mevcut action'lar
`notify=telegram` etiketine bağlıysa yeni trigger'ları da kapsayabilir.

## Temel OS template'leri

Her hosta yalnızca bir OS/iletişim sürümü bağla:

| Sistem | Pasif | Aktif |
| --- | --- | --- |
| Linux | essential-items-linux.yaml | essential-items-linux-active.yaml |
| Windows | essential-items-windows.yaml | essential-items-windows-active.yaml |

CPU kullanımı, kullanılabilir RAM (Grafana'da 100−değer ile kullanım), uptime,
ağ ve ayrı dosya sistemi/sürücü keşfi bulunur. Her sürücüde doluluk, boş alan ve
toplam alan tutulur. Agent verisi yaşı `lastclock(system.uptime)` üzerinden
merkezde hesaplanır; proxy kesildiğinde son uptime örneğinin yaşı büyür.

Geniş process master item'ı ve eski tüm-process keşfi varsayılan olarak devre
dışıdır; geçmişleri silinmez. Eski keşfin oluşturduğu dependent item'lar yeni
örnek alamaz. Bunlar yerine aşağıdaki açık listeler kullanılmalıdır. Legacy
playlist modunun tüm-process paneli bu yüzden veri göstermeyebilir; müşteri
modunda bu panel zaten yoktur.

## Kritik Windows servisleri

`required-windows-services.yaml` veya aktif agent için
`required-windows-services-active.yaml` import et ve temel OS template'ine ek
olarak bağla. Host üzerinde `{$REQUIRED.SERVICES}` macro'sunu JSON liste olarak
ayarla. Varsayılan `[]`, hiçbir servis seçili olmadığı anlamına gelir.

Başlangıç listeleri — yalnızca ilgili role sahip hostlarda kullan:

| Rol | Örnek macro değeri |
| --- | --- |
| AD Domain Controller | `["NTDS","Netlogon","Kdc","W32Time"]` |
| Windows DNS sunucusu | `["DNS"]` |
| Windows SMB dosya sunucusu | `["LanmanServer"]` |
| Bağımsız Hyper-V hostu | `["vmms"]` |

Bir hostta birden fazla rol varsa adları tek listede birleştir. Display name
yerine gerçek servis adını kullan. Önce Services/PowerShell üzerinden mevcut
servis adlarını doğrula. Hyper-V hostunda `vmms` kontrolü VM envanteri veya VM
sağlığı izlemesinin yerine geçmez; AD servis kontrolü de replikasyon testi değildir.

Keşif, hostta bulunan tüm servisleri taramaz; macro'daki adları item prototype'a
çevirir. Böylece ilk anda mevcut olmayan zorunlu servis de kontrol edilir.
`service.info[NAME,state]` değeri 0 (Running) dışında üç ardışık ölçümde (bir dakikalık aralıklarla) kaldığında High
trigger oluşur. Servis yoksa agent'ın döndürdüğü non-running/missing state de
sorun olarak değerlendirilir. Çalışmaması beklenen servisleri listeye ekleme.

## Kritik process'ler — Linux ve Windows

`required-processes.yaml` veya `required-processes-active.yaml` dosyasını bağla.
`{$REQUIRED.PROCESSES}` macro'suna teknik process adlarını JSON liste olarak yaz:

```json
["nginx", "mysqld"]
```

Windows'ta örnek biçim `application.exe`; gerçek adı doğrula. Her ad için
`proc.num[NAME]` ile adet ölçülür. Üç ölçümlük pencerede en az üç örneğin tamamında adet 0 ise High trigger
oluşur. İlk anda process'in hiç başlamamış olması da algılanır. Bu temel profil
process CPU/RAM detayını veya uygulamanın işlevsel olarak çalıştığını kanıtlamaz.
Listeler en fazla 100 ad içerir; boş/tekrarlanan veya item key'e uygun olmayan
adlar discovery sırasında reddedilir. Liste boşsa hiçbir process kontrol edilmez.

## Web sitesi

`website-availability.yaml` template'ini her web sitesi için ayrı bir hosta bağla.
Hostu ilgili müşteri grubuna ekle, müşterinin proxy'si üzerinden izlenecek şekilde
ayarla. Uygulamadan önce `{$WEB.URL}` macro'sunu gerçek HTTPS URL'siyle değiştir.
Varsayılan `example.invalid` kasıtlı olarak çalışan bir müşteri adresi değildir.

- Dakikada bir GET kontrolü; 15 saniye timeout, iki deneme.
- 200–299 yanıtı beklenir; redirect takip edilir.
- İsteğe bağlı `{$WEB.REQUIRED.TEXT}` yanıt içeriğinde aranacak regex'tir.
- TLS peer ve hostname doğrulaması açıktır; bu kontrolleri kapatma.
- Üç ölçümlük pencerede en az üç başarısız örnek veya beş dakika kontrol verisi
  yokluğu alarm üretir.
- Önceden sertifika bitiş uyarısı, kimlik doğrulama, çok adımlı login ve dışarıdan
  erişilebilirlik bu profilin kapsamında değildir. Proxy içinden erişimin başarılı
  olması, sitenin internetten de erişilebilir olduğunu kanıtlamaz.

## Dell/HPE ve sanallaştırma

Vendor OID/health değerlerini yeniden tanımlamak yerine resmi **7.4**
şablonları kullanılacak. Her fiziksel cihazın yönetim arayüzü için ayrı Zabbix
hostu ve SNMP interface gerekir. Bu hostlar müşteri grubunda tutulabilir; OS
hostu ile aynı fiziksel cihaza ait olduklarını envanter etiketiyle ilişkilendir.
Bir yönetim hostu ve bir OS hostu, iki fiziksel cihaz anlamına gelmez.

| Altyapı | Resmi template / yol | Durum |
| --- | --- | --- |
| Dell R740 / iDRAC | Dell iDRAC by SNMP | SNMP erişimi/yetki/sürüm pilotta doğrulanacak |
| HP/HPE Gen8–9 / iLO | HP iLO by SNMP | Model/firmware ve SNMP desteği doğrulanacak |
| ESXi 7+ | VMware entegrasyonu; ESXi API'ye doğrudan erişim | vCenter kapsam dışında; hesap/yetki ve collector ayarı gerekli |
| Hyper-V / Windows Server 2019+ | Temel Windows + seçilen servisler | Cluster yok; tam VM envanter entegrasyonu ayrı aşama |
| Veeam Community/Enterprise | Sürüme ve API erişimine göre seçilecek | Bildirilen “7/8” sürümleri teyit bekliyor; hazır varsayılmıyor |

Resmi kaynaklar:
[Dell 7.4 template](https://github.com/zabbix/zabbix/blob/release/7.4/templates/server/dell_idrac_snmp/template_server_dell_idrac_snmp.yaml),
[HPE 7.4 template](https://github.com/zabbix/zabbix/blob/release/7.4/templates/server/hp_ilo_snmp/template_server_hp_ilo_snmp.yaml),
[VMware 7.4 rehberi](https://www.zabbix.com/documentation/7.4/en/manual/guides/monitor_vmware),
[Windows servisleri](https://www.zabbix.com/documentation/7.4/en/manual/config/items/itemtypes/zabbix_agent/win_keys).

Veeam servisine ait tek bir process veya Windows servis kontrolü başarılı yedek,
immutability veya geri yükleme başarısı olarak sunulmaz. API bilinmeden sahte
başarılı yedek ölçümü üretilmez.

## Dashboard ve geri alma

Müşteri modunda ortak cihaz dashboard'undaki **Service and website checks**
bağlantısı seçilen Group/Host ile ikinci ortak dashboard'u açar. Servis state,
process sayısı, web senaryosu başarısız adımı ve yanıt süresi burada görünür.
Profil bağlanmamış veya veri gelmeyen panel UNKNOWN olabilir; bu durumda
“her şey sağlıklı” çıkarımı yapılmamalıdır.

Listeyi güncellediğinde discovery'yi Execute now ile veya beş dakikalık döngüyle
yenile. Listeden kaldırılan kontrollerin item'ları devre dışı kalır, geçmişleri
silinmez. Geri almak için yeni profili veya ilgili item/trigger'ları devre dışı
bırak; Unlink and clear kullanma. Eski process görünümü gerekiyorsa eski master
item ve process discovery kuralını tekrar etkinleştir; geniş keşif yükünü dikkate al.

Canlı import ve gerçek servis durumu pilotta doğrulanmalıdır. Bu dosyaların
hazırlanması hiçbir agent/proxy servisini yeniden başlatmaz.
