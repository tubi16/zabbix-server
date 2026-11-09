# Agent ile dinamik arayüz

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
