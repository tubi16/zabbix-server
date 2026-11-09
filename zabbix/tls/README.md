# Sunucudan host kaydı ve TLS-PSK

Bu klasör sadece sunucu işlerini içerir: PSK üretimi, Zabbix API kaydı,
SSH aktarımı, bağlantı doğrulaması ve işlem kayıtları. Agent kurulum kodu
ayrı agent reposundaki `install.py` dosyasındadır.

## Ön koşullar

Sunucuda Python 3 ve çalışan bu repo Compose servisleri; `.env` içinde Zabbix
`Admin` hesabının parolası (`ZABBIX_ADMIN_PASSWORD`) gerekir. Agent reposu
sunucu yöneticisinin bilgisayarında klonlu olmalıdır. Hedefte Python 3,
systemd, kurulu agent/agent2, SSH ve sudo erişimi gerekir. Firewall veya SSH
ayarları script tarafından değiştirilmez.

## Kullanım

Sunucu reposunun kökünde normal kullanıcı olarak:

```sh
python3 zabbix/tls/enroll.py --host YeniPC --address 172.16.53.150 --ssh kullanici@172.16.53.150 --server 172.16.53.132 --agent-source /tam/yol/agent-reposu
```

`--address` hedef agent IP'sidir. `--server` agent'ın gördüğü sunucu kaynak
IP'si/alt ağıdır; NAT ve Tailscale varsa buna göre belirlenir. Sunucunun kendi
bilgisayarındaki agent için `--ssh` yerine `--local`, kaynak olarak Docker
alt ağı kullanılabilir. Adresleri kendi ortamına göre değiştir.

Önizleme için `--plan` ekle. Diğer seçenekler: `--agent auto|classic|agent2`,
`--port 10050`, `--group 'Linux servers'`, `--template 'Essential Items'`.
Host adı ASCII harf/rakam, nokta, alt çizgi veya tireyle 1–64 karakterdir.
Agent repo yolu verilmezse sunucu repo kökünün yanındaki `staj-agent` aranır;
repo isimleri/konumları farklıysa `--agent-source` zorunludur.

## Güvenli geçiş sırası

1. Agent kaynak dosyası, grup/template, mevcut host ve Docker test aracı doğrulanır.
2. `private/HOST.psk` içinde cihaza özel 256-bit anahtar üretilir veya mevcut anahtar kullanılır.
3. Hedefe yalnızca agent `install.py` dosyası ve o cihazın PSK'sı aktarılır.
4. Agent ayarları yedeklenir, doğrulanır ve ilgili servis yeniden başlatılır.
   Geçiş aşamasında şifresiz+PSK kabul edilir; zaten strict agent gevşetilmez.
5. Sunucunun içinden `zabbix_get` ile PSK `agent.ping` isteği yapılır.
6. Test geçerse host oluşturulur/güncellenir; PSK iki yönde zorunlu yapılır.
   Mevcut grup, template ve etiketler korunur; gerekli olanlar eklenir.
7. Agent strict yapılır; PSK ile başarı ve şifresiz bağlantı reddi doğrulanır.

Admin parolası ve API oturumu sunucuda kalır. PSK test aracına stdin üzerinden
aktarılır; komut satırına veya loglara konmaz. Sunucudaki geçici test dosyası
`0600` izinlidir ve testten sonra silinir. Hedefteki kurulum aşamaları sudo
parolasını iki kez isteyebilir; script'in tamamını sudo ile çalıştırma.

Bir host için tekrar çalıştırmada anahtar ve host ID korunur. Başka bir araçla
kurulmuş şifreleme veya farklı mevcut PSK otomatik ezilmez. Aynı host için
eşzamanlı iki işlem kilitle engellenir. İşlem kayıtları `private/` altında
Git'e alınmadan tutulur. Bu dizini yedekle ve repo ayrılırken geçmiş anahtarları
güvenli biçimde taşı; kaybettiysen yeni anahtar üretip mevcut hosta körlemesine
uygulama.

Dashboard otomasyonu varsayılan `Linux servers` grubundaki etkin hostları
60 saniye içinde alır. Farklı grup kullanırsan host-sync filtresini ve salt
okunur Zabbix hesabının grup izinlerini de güncelle. Mevcut devre dışı hostlar
kayıt scripti tarafından yeniden etkinleştirilmez.

## Hata ve geri alma

İlk PSK testi başarısızsa Zabbix TLS modu değiştirilmez. Nedenini giderip aynı
komutu tekrar çalıştırabilirsin. Server kaydından sonraki bir hata otomatik
şifresiz geri dönüş yapmaz; işlem başarıyla tamamlandı olarak işaretlenmez.

Önce hedefte agent scriptinin yazdığı ilk config yedeğini geri yükle ve agent'ı
yeniden başlat. Sonra aynı `enroll.py` komutuna `--rollback` ekle. Önceden var
olan hostun TLS modu geri yüklenir; yeni host silinmeden devre dışı bırakılır.
Grup/template eklemeleri ve IP güncellemesi geri alınmaz; gerekiyorsa arayüzden
düzenle. Anahtarlar, metrik geçmişi ve host kaydı silinmez.

`update-server-psk.py` önceki elle geçiş kayıtları için yardımcı araçtır;
agent dosyası kurmaz ve yeni otomasyonun yerine kullanılmasına gerek yoktur.

## Test

```sh
python3 -B -m unittest discover -s zabbix/tls -p 'test_*.py'
```

Testler agent reposu klonlu olmasa da çalışır; harici kaynak yolu test fixture'ıyla
verilir ve SSH/sudo/API değişiklikleri mock edilir. Gerçek agent TLS testleri
ayrı agent reposundadır.
