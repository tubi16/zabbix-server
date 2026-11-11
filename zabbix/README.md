# Linux ve Windows agent template'leri

Zabbix 7.4+ için işletim sistemi ve agent çalışma biçimine göre dosya seç:

| Sistem | Pasif agent | Aktif agent |
| --- | --- | --- |
| Linux | `templates/essential-items-linux.yaml` | `templates/essential-items-linux-active.yaml` |
| Windows | `templates/essential-items-windows.yaml` | `templates/essential-items-windows-active.yaml` |

Dosyayı **Data collection → Templates → Import** üzerinden içe aktar.
**Create new / Update existing** açık, **Delete missing** kapalı olmalı.
Hosta yalnızca işletim sistemine ve mevcut agent ayarına uygun tek sürümü bağla.
Kurulum ve import scriptleri değiştirilmedi; Windows dosyaları arayüzden import edilir.

Linux dosyaları mevcut template ve item UUID'lerini, `Essential Items` /
`Essential Items Active` teknik adlarını korur; görünen adları
`Essential Items Linux` / `Essential Items Linux Active` olur. Böylece mevcut
Linux template'i güncellenir ve geçmiş veriler korunur. Eski
`essential-items.yaml` script uyumluluğu için aynen bırakıldı; mevcut import
scripti bu eski dosyayı kullanır ve görünen adı tekrar eski adına döndürebilir.
Windows template'leri ayrı teknik adlara ve UUID'lere sahiptir.

Windows CPU kullanımını `system.cpu.util` ile doğrudan toplar. Disk için
`{$WINDOWS.SYSTEM.DRIVE}` varsayılanı `C:`; farklı sürücü için host macros alanından
değiştir. Bu template yalnızca seçilen sürücüyü izler. Ağ keşfi `net.if.discovery`
kullanır ve arayüz başına trafik üretir; varsayılan rotayı seçmez.
`{$NET.IF.IFNAME.MATCHES}` / `{$NET.IF.IFNAME.NOT_MATCHES}` ile arayüzleri filtrele.
Process belleği `wkset` alanından, kullanıcı CPU süresi milisaniyeden saniyeye
çevrilerek alınır. CPU Load Windows'ta processor queue length anlamına gelir.
CPU, disk, RAM, veri gelmemesi ve yeniden başlama bildirimleri korunur.

Windows kaynakları:
[agent anahtarları](https://www.zabbix.com/documentation/7.4/en/manual/config/items/itemtypes/zabbix_agent/win_keys),
[process alanları](https://www.zabbix.com/documentation/7.4/en/manual/appendix/items/proc_get).

Geri alma: Windows hostunda eklenen template'i **Unlink** ile ayır; geçmişi
silmemek için **Unlink and clear** kullanma. Linux görünen adlarını geri almak
için mevcut import scriptini kullandığın aktif/pasif seçeneğiyle çalıştır.

## Linux agent ile dinamik arayüz

Template yalnızca standart Linux Zabbix agent özelliklerini kullanır.
Ek script, UserParameter veya servis yeniden başlatması gerekmez.
Agent /proc/net/route dosyasını okuyabilmeli; vfs.file.contents[] ve net.if.in/out[]
anahtarlarına izin verilmiş olmalıdır. Template pasif agent erişimi kullanır.

templates/essential-items.yaml dosyasını import ederken mevcut öğeleri güncelle ve
yenileri oluştur; Delete missing kapalı kalsın. Template'i hosta bağla.
IPv4 routing table dakikada bir okunur. Keşiften sonra iki hız örneği için
bir dakika daha bekle. Dashboard item adları değişmez. Eski eth0 item'ları
geçmişleri silinmeden devre dışı bırakılır. Arayüz değişince önceki keşfedilen
item'lar devre dışı bırakılır; geçmişleri saklanır.

En düşük metrikli UP varsayılan rota ana IPv4 tablosundan seçilir.
IPv6, policy routing, VPN'in iki /1 rota kullanması ve eşit metrikli çoklu çıkışlar
kapsanmaz. Arayüzün LAN dahil toplam trafiği ölçülür. Agent doğrudan hostta
çalışmalıdır; Docker bridge içindeyse kendi ağ ad alanının rotalarını görür.

Geri alma: yeni discovery kuralını ve ürettiği item'ları devre dışı bırak;
eski net.if.in[eth0] ve net.if.out[eth0] item'larını tekrar etkinleştir.
IPv4 routing table item'ını devre dışı bırak. Geçmiş verileri silme.

## Trigger ve Telegram bildirimleri

Pasif ve aktif template aynı beş trigger'ı içerir:

| Kontrol | Problem | Düzelme | Seviye |
| --- | --- | --- | --- |
| CPU kullanımı | 5 dakika boyunca > %90 | 5 dakika boyunca < %80 | Warning |
| Kök disk doluluğu | 5 dakika boyunca > %90 | 5 dakika boyunca < %85 | High |
| Kullanılabilir RAM | 5 dakika boyunca < %10 | 5 dakika boyunca > %15 | Warning |
| Agent verisi | 5 dakika uptime verisi yok | Veri yeniden gelir | High |
| Yeniden başlama | Uptime < 10 dakika | Uptime >= 10 dakika | Information |

Eşikler template/host **Macros** alanından değiştirilebilir. Veri gelmemesi
hostun kapalı olduğunu kesinleştirmez; agent, proxy veya bağlantı arızası da olabilir.
CPU kullanımı için ayrı bir item eklenir; mevcut CPU Load item'ı korunur.

Sunucuda `zabbix-server` dizininden kullanılan sürümü güncelle:

```sh
python3 scripts/import_template.py
python3 scripts/import_template.py --active
```

Yalnızca kullandığın sürümün komutunu çalıştır; iki sürümü aynı hosta bağlama.
İçe aktarımda **Delete missing** kapalı kalmalıdır.

Telegram alıcısı ve mesajları sonradan arayüzden ayarlanır. `notify=telegram`
etiketi tek başına bildirim göndermez; aşağıdaki action bağlantıyı kurar:

1. BotFather üzerinden bot oluştur; özel sohbet için bota `/start` gönder veya
   botu hedef gruba ekle. Hedef chat ID'sini edin; grup ID'sindeki eksi işaretini koru.
2. **Alerts → Media types → Telegram** bölümünde webhook'u etkinleştir.
   Mevcut değilse aşağıdaki resmî sayfadan **7.4** sürümünü seçip media type'ı
   import et. Bot token'ını `api_token` alanına yalnızca arayüzden gir.
3. **Users → Users → ilgili kullanıcı → Media** altında Telegram ekle;
   **Send to** alanına chat ID gir, aktif zamanı ve Information dahil istenen
   seviyeleri seç. Kullanıcının izlenen host gruplarına en az okuma yetkisi olmalı.
4. **Alerts → Actions → Trigger actions** altında `Essential Items - Telegram`
   action'ı oluştur. Koşulu **Tag value: notify equals telegram** yap.
   **Operations** altında kullanıcıya **Send only to: Telegram** ile mesaj ekle.
   Adımları `1–1` tutarak tek problem mesajı gönder.
5. **Recovery operations** altında aynı kullanıcıya Telegram mesajı ekle.
   Problem/düzelme metinlerini media type'ın **Message templates** alanından veya
   action içindeki özel mesaj alanından düzenle. Action'ı etkinleştir.
6. Media type'ın **Test** düğmesiyle iletimi doğrula. Uçtan uca doğrulama için
   ayrı bir test hostunda etiketli geçici trigger ile problem ve düzelme üret;
   **Reports → Action log** üzerinden iki mesajın durumunu kontrol et.

Mevcut action'larda aynı alıcıya bildirim varsa koşullarını kontrol ederek
çift mesajı önle. Token'ı repoya, ekran görüntüsüne veya komut çıktısına koyma.
Bu işlem servis yeniden başlatması gerektirmez.

Resmî kurulum: https://www.zabbix.com/integrations/telegram (7.4 seçilmeli).

Geri alma: önce `Essential Items - Telegram` action'ını devre dışı bırak.
Gerekirse template'teki beş yeni trigger'ı devre dışı bırak; item'ları veya
geçmiş verileri silme.
