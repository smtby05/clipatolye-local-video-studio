# ClipAtölye

Bilgisayarında çalışan, Türkçe video klip stüdyosu. Arayüz ve iş kuyruğu yereldir; yüklenen videolar `work/media` içinde, oluşturulan MP4 klipler normalde `outputs` içinde saklanır. Windows bu klasöre yazmayı engellerse uygulama yeni dosyaları `work/generated-outputs` içine kaydeder ve önceki `outputs` dosyalarını da görüntülemeye devam eder.

## Başlatma

Windows'ta `Başlat.bat` dosyasına çift tıkla. Tarayıcıda `http://127.0.0.1:8765` açılır. Yerel Whisper motoru Python 3.12 ile çalışır. Uygulama FFmpeg/FFprobe, Whisper modeli ve Python paketlerini proje içindeki `work` alanında tutar; yönetici izni ve sistem PATH ayarı gerekmez.

Gerekli medya araçları ve temel Whisper modeli bu kopya için kurulmuştur. Kurulum dosyaları proje içindeki `work` dizinindedir; yönetici izni veya sistem PATH değişikliği yapılmaz.

## Kurulan yerel araçlar

`work/python-packages` temel Python bağımlılıklarını, `work/runtime-packages-v3` yerel Whisper motorunu; `work/tools` FFmpeg/FFprobe programlarını; `work/models` Whisper dil modelini içerir. İlk kurulum ve model indirmesi internet bağlantısı ile birkaç yüz MB boş disk alanı gerektirir. Video bundan sonra bu bilgisayarda işlenir.

## Mevcut işlevler

- yt-dlp destekli herkese açık video bağlantıları veya yerel video/ses dosyası kaynağı (site erişimi, oturum ve DRM kısıtları geçerlidir)
- İndirme çözünürlüğü seçimi ve 9:16, 1:1, 16:9 çıktı
- Videoyu eşit aralıklara bölme, süreli klip adayları oluşturma veya özel zaman aralığı seçme
- Kaynak video için tam süreli tarayıcı oynatıcısı (yerel dosya veya desteklenen YouTube gömülü oynatıcı; tam ekran kontrolü oynatıcıda)
- FFmpeg ile gerçek MP4 klip dışa aktarımı ve tarayıcıda önizleme/indirme
- Dikey çıktıda kırpma, bulanık video arka planı veya yüklenen görsel/video arka planı; arka planı tam ekran ya da üst/alt yarılarda kullanma
- 1–3 saniyelik yumuşak baş-son döngü geçişi; aynı geçiş karesi videonun iki ucunda buluşur
- Altyazı ve isteğe bağlı başlık için font ve üst/alt konum seçenekleri
- Projeler `work/projects.json` içinde kalıcı saklanır; klipler yazılabilir çıktı klasöründe tutulur. Windows klasör izinleri yüzünden `outputs` kullanılamazsa `work/generated-outputs` devreye girer. Eski `outputs` dosyaları okunabilir kalır. Arayüz tercihleri tarayıcıda korunur.
- Altyazı SRT dosyasını indirme, tarayıcıda düzeltme ve kaydetme
- Video başlığı/süresi/çözünürlüğü, işlem adımları ve araç durumunu gösterme
- faster-whisper ile yerel konuşma dökümü, konuşma yoğunluğu ve vurgu sözcüklerinden tahmini öne çıkan an puanı, kelime zamanlı SRT altyazıları ve isteğe bağlı altyazı gömme

## Aşamalı geliştirme

“Öne çıkanlar” gerçek YouTube görüntülenme/izleyici tutma verisi değildir; yalnızca konuşma metninden tahmin yapılır. Platform analitiğini kullanmak için kanal sahibi OAuth erişimi ve YouTube Analytics entegrasyonu gerekir. X/LinkedIn/bülten taslakları ve tam video editörü henüz kapsamda değildir.

YouTube indirme özelliğini yalnızca indirme hakkına sahip olduğun içeriklerde kullan. Video işleme ve dosyalar bu bilgisayarda kalır. (yt-dlp ağ üzerinden kaynağa erişir.)
