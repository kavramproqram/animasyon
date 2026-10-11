# -*- coding: utf-8 -*-
"""
Kavram Animasyon — Türkçe yardım sistemi

  * TIPS            : her düğme / ayar için açıklama metinleri
  * set_tip / tip   : bir widget'a ya da QAction'a açıklama bağlar
  * TooltipManager  : fare bir öğenin üzerinde 2 saniye DURURSA açıklamayı gösterir
                      (Qt'nin sabit 700 ms gecikmesine bağlı değildir; kendi sayacı vardır)
  * GuideDialog     : "Hızlı başlangıç" kılavuzu (video yükleme, çizim, hareket verme, dışa aktarma)
"""

from PyQt5.QtCore import Qt, QObject, QTimer, QElapsedTimer, QEvent, QPoint, QSettings
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (QApplication, QToolTip, QMenu, QToolButton, QDialog, QVBoxLayout, QHBoxLayout,
                             QTextBrowser, QCheckBox, QPushButton)

TIP_PROP = "kavram_tip"
TIP_DELAY_MS = 2000
SETTINGS_ORG, SETTINGS_APP = "Kavram", "KavramAnimasyon"

# --------------------------------------------------------------------------------------
#  Açıklama metinleri:  anahtar -> (başlık, açıklama, kısayol)
# --------------------------------------------------------------------------------------
TIPS = {
    # --- araçlar --------------------------------------------------------------------------
    'select': ("Seç / Taşı", "Nesneye tıklayarak seçersin, sürükleyerek taşırsın. Seçili nesnenin köşe "
               "kutucuklarıyla boyutunu, üstteki yuvarlakla dönüşünü değiştirirsin. Boş yerde sürükleyip "
               "çerçeveyle birden çok nesne seçebilirsin. Shift: seçime ekle/çıkar. Ctrl basılıysa "
               "ızgaraya yapışma geçici kapanır.", "V"),
    'pen': ("Kalem", "Fareyle serbest çizim yapar. Çizgiyi bırakınca nokta sayısı otomatik azaltılır ve "
            "düzenlenebilir bir 'Serbest' nesnesi olur.", "P"),
    'line': ("Çizgi", "Sürükleyerek düz çizgi çizer. Shift basılıysa açı 15 derecelik adımlara kilitlenir.", "L"),
    'rect': ("Dikdörtgen", "Sürükleyerek dikdörtgen çizer. Shift: kare. Köşe yuvarlaklığını sonradan "
             "'Matematiksel parametreler' bölümünden ayarlarsın.", "R"),
    'ellipse': ("Elips", "Sürükleyerek elips çizer. Shift: tam daire.", "E"),
    'polygon': ("Çokgen", "Merkezden dışarı sürükleyerek düzgün çokgen çizer. Kenar sayısını üstteki "
                "'Kenar' kutusundan seçersin.", "G"),
    'star': ("Yıldız", "Merkezden dışarı sürükleyerek yıldız çizer. Uç sayısı üstteki 'Kenar' kutusundan gelir; "
             "iç yarıçap sonradan parametrelerden değiştirilebilir.", "S"),
    'spline': ("Eğri (spline)", "Tıkladığın noktalardan geçen yumuşak bir eğri çizer. Bitirmek için çift tıkla, "
               "sağ tıkla ya da Enter'a bas (Ctrl+Enter: kapalı eğri). İlk noktaya tıklarsan eğri kapanır. "
               "Backspace: son noktayı siler. Esc: iptal.", "B"),
    'eraser': ("Silgi", "Üzerinden geçtiğin nesneyi tamamen siler. Geri almak için Ctrl+Z.", "X"),
    'pan': ("Kaydır", "Tuvali sürükleyerek kaydırır. Aynı işi her araçta fare ORTA tuşuyla da yapabilirsin.", "H"),
    'eyedrop': ("Damlalık", "Tuvaldeki (video dahil) bir noktanın rengini alır ve seçili çizgi/dolgu rengi yapar.", "I"),
    'math': ("Matematiksel nesne ekle", "Formülle nesne oluşturur: y=f(x) fonksiyon, x(t),y(t) parametrik, "
             "r(a) kutupsal, ya da koordinatla çizgi/elips/çokgen. Hazır formüller listesinden de seçebilirsin.", "M"),
    # --- üst seçenek çubuğu ------------------------------------------------------------------
    'grid_spin': ("Grid boyutu", "Izgara hücresinin piksel boyutu. Sistemi yormamak için tuval boyutuna göre bir "
                  "ALT SINIR vardır (en az 8 px); bu sınırın altına inemezsin. Çok yakınlaştırılmış/uzaklaştırılmış "
                  "görünümde çizgiler kendiliğinden seyreltilir.", None),
    'grid_show': ("Gridi göster", "Izgarayı görünür / gizli yapar. Dışa aktarmaya etkisi yoktur; orada ayrı seçenek var.", "Ctrl+G"),
    'snap': ("Izgaraya yapış", "Çizerken ve taşırken noktalar ızgara çizgilerine yapışır. Ctrl basılı tutarak "
             "geçici olarak kapatabilirsin.", "Ctrl+Shift+G"),
    'width': ("Çizgi kalınlığı", "Yeni çizilen nesnelerin (ve seçili nesnelerin) çizgi kalınlığı, piksel cinsinden. 0 = çizgisiz.", None),
    'sides': ("Kenar / uç sayısı", "Çokgen ve yıldız araçları için kenar (uç) sayısı.", None),
    'scope': ("Çizim kapsamı", "Çizdiğin nesne hangi karelerde görünsün?\n"
              "• Tüm karelerde: baştan sona.\n• Bu kareden sonuna: şu andan itibaren.\n"
              "• Sadece bu karede: yalnızca bu kare (video üzerine kare kare çizim için ideal).", None),
    'autokey': ("Oto-anahtar", "Açıkken bir nesneyi taşıdığında/döndürdüğünde/ölçeklediğinde o karede otomatik "
                "anahtar kare oluşur. Hareket vermenin en kolay yolu: kareyi seç, nesneyi taşı, başka kareye "
                "geç, tekrar taşı.", None),
    'onion': ("Soğan kabuğu", "Önceki kareleri kırmızı, sonraki kareleri yeşil hayalet olarak gösterir; "
              "hareketin akışını görmeni sağlar. Oynatırken otomatik kapanır.", "O"),
    'onion_n': ("Soğan kabuğu kare sayısı", "Önce/sonra kaç kare hayalet gösterilsin (1-6).", None),
    'bg_slider': ("Arka plan görünürlüğü", "Yüklediğin video/görüntünün ne kadar belirgin olacağını ayarlar (0-100).", None),
    # --- renk paneli -------------------------------------------------------------------------
    'c_stroke': ("Çizgi rengi", "Hangi rengi düzenlediğini seçer. Bu düğme seçiliyken kaydırıcılar, hex kutusu "
                 "ve palet çizgi rengini değiştirir.", None),
    'c_fill': ("Dolgu rengi", "Dolgu rengini düzenlemeyi seçer. Renk seçince 'Dolgu açık' otomatik işaretlenir.", None),
    'fill_on': ("Dolgu açık", "Nesnenin içi dolgu rengiyle boyansın mı? Kapalıysa sadece çizgi görünür.", None),
    'c_h': ("Ton", "Rengin türü (kırmızı, sarı, yeşil...). 0-359 derece.", None),
    'c_s': ("Doygunluk", "0 = gri/solgun, 255 = canlı renk.", None),
    'c_v': ("Parlaklık", "0 = siyah, 255 = en parlak.", None),
    'c_a': ("Opaklık", "0 = tamamen saydam, 255 = tamamen opak.", None),
    'c_hex': ("Hex renk kodu", "#RRGGBB biçiminde renk yaz ve Enter'a bas. Örnek: #ff8800.", None),
    'c_wheel': ("Renk çemberi", "Renk çemberi ve parlaklık çubuğu olan seçici pencereyi açar. Hex kodu yapıştırabilirsin "
                "(Ctrl+V).", None),
    'c_palette': ("Renk paleti", "Sol tık: çizgi rengi olarak al. Sağ tık: dolgu rengi olarak al.", None),
    'c_history': ("Son kullanılan renkler", "Tıklayınca o rengi geri çağırır. Sağ tık: hex kodunu kopyala.", None),
    # --- nesne özellikleri --------------------------------------------------------------------
    'name': ("Nesne adı", "Nesneler listesinde görünen ad. İstediğin gibi değiştir.", None),
    'tr_x': ("Konum X", "Nesnenin orijininin yatay konumu (piksel). Anahtar kareli nesnede yalnızca bu kare etkilenir.", None),
    'tr_y': ("Konum Y", "Nesnenin orijininin dikey konumu (piksel). Aşağı doğru artar.", None),
    'tr_rot': ("Döndürme", "Derece cinsinden dönüş. Pozitif değer saat yönüdür.", None),
    'tr_sx': ("Ölçek X", "Yatay büyütme/küçültme. 1 = orijinal boyut. Negatif değer aynalar.", None),
    'tr_sy': ("Ölçek Y", "Dikey büyütme/küçültme. 1 = orijinal boyut.", None),
    'key_add': ("Anahtar kare ekle", "Seçili nesnenin şu anki konum/dönüş/ölçeğini bu karede 'anahtar' olarak kaydeder. "
                "İki anahtar arasında nesne kendiliğinden hareket eder. En az iki farklı karede anahtar gerekir.", "K"),
    'key_del': ("Anahtar kareyi sil", "Bu karedeki anahtarı kaldırır; hareket komşu anahtarlar arasında yeniden hesaplanır.", "Shift+K"),
    'ease': ("Geçiş türü", "Bu anahtardan sonraki anahtara kadar hareketin hız eğrisi: doğrusal, yumuşak, "
             "yavaş başla, yavaş bitir ya da sabit tut (aniden atlar).", None),
    'life_start': ("Görünür: ilk kare", "Nesne hangi kareden itibaren görünsün.", None),
    'life_end': ("Görünür: son kare", "Nesne hangi kareye kadar görünsün. 'son kare' = animasyon sonuna kadar.", None),
    'params': ("Matematiksel parametreler", "Nesneyi tanımlayan sayılar ve formüller. Değiştirince nesne anında yeniden çizilir. "
               "Formüllerde sin, cos, tan, sqrt, exp, log, abs, pi, e ve ^ kullanılabilir.", None),
    'layers': ("Nesneler listesi", "Üstteki satır en üstteki nesnedir. Tıklayarak seç (Ctrl/Shift ile çoklu), "
               "kutucukla göster/gizle. Sıralamayı Ctrl+] (öne) ve Ctrl+[ (arkaya) ile değiştir.", None),
    # --- zaman çizelgesi -----------------------------------------------------------------------
    't_first': ("İlk kare", "Animasyonun başına gider.", "Home"),
    't_prev': ("Önceki kare", "Bir kare geri gider. Basılı tutarsan sürekli geri gider.", "←"),
    't_play': ("Oynat / Durdur", "Animasyonu (ve varsa arka plan videosunu) FPS hızında oynatır.", "Boşluk"),
    't_next': ("Sonraki kare", "Bir kare ileri gider. Basılı tutarsan sürekli ilerler.", "→"),
    't_last': ("Son kare", "Animasyonun sonuna gider.", "End"),
    't_frame': ("Geçerli kare", "Şu an hangi karedesin. Sayı yazarak doğrudan o kareye atlayabilirsin.", None),
    't_total': ("Toplam kare", "Animasyonun uzunluğu. Videoyu yüklerken video kare sayısıyla eşleştirmeyi önerir.", None),
    't_fps': ("FPS", "Saniyedeki kare sayısı. Oynatma hızını ve dışa aktarılan videonun hızını belirler.", None),
    't_loop': ("Döngü", "Sona gelince başa dönerek oynatmaya devam eder.", None),
    'timeline': ("Zaman çizelgesi", "Tıkla/sürükle: kareye git. Tekerlek: kaydır. Ctrl+tekerlek: yakınlaştır. "
                 "Sarı eşkenar dörtgenler seçili nesnenin anahtar kareleridir; yeşil çubuk görünürlük aralığıdır; "
                 "mavi şerit arka plan videosunun kapladığı karelerdir.", None),
    # --- menü eylemleri -------------------------------------------------------------------------
    'a_new': ("Yeni proje", "Çözünürlük, grid ve FPS seçerek boş bir proje başlatır.", "Ctrl+N"),
    'a_open': ("Aç", "Kayıtlı bir .kanim proje dosyasını açar.", "Ctrl+O"),
    'a_save': ("Kaydet", "Projeyi kaydeder. Kayıt güvenlidir: önce geçici dosyaya yazılır, sonra yerine konur.", "Ctrl+S"),
    'a_saveas': ("Farklı kaydet", "Projeyi yeni bir adla kaydeder.", "Ctrl+Shift+S"),
    'a_export': ("Dışa aktar", "Kare aralığını PNG dizisi ya da MP4 video olarak yazar. Arka plan videosunu ve "
                 "gridi dahil edebilirsin.", "Ctrl+E"),
    'a_png': ("Bu kareyi PNG kaydet", "Yalnızca şu anki kareyi resim olarak kaydeder.", None),
    'a_quit': ("Çıkış", "Programı kapatır (kaydedilmemiş değişiklik varsa sorar).", "Ctrl+Q"),
    'a_undo': ("Geri al", "Son değişikliği geri alır.", "Ctrl+Z"),
    'a_redo': ("İleri al", "Geri alınan değişikliği yeniden uygular.", "Ctrl+Y"),
    'a_copy': ("Kopyala", "Seçili nesneleri panoya alır.", "Ctrl+C"),
    'a_paste': ("Yapıştır", "Kopyalanan nesneleri bir grid hücresi kaydırarak yapıştırır.", "Ctrl+V"),
    'a_dup': ("Çoğalt", "Seçili nesnelerin kopyasını hemen yanına oluşturur.", "Ctrl+D"),
    'a_del': ("Sil", "Seçili nesneleri siler.", "Del"),
    'a_all': ("Tümünü seç", "Bu karede görünen bütün nesneleri seçer.", "Ctrl+A"),
    'a_front': ("Öne getir", "Seçili nesneyi bir kat öne alır.", "Ctrl+]"),
    'a_back': ("Arkaya gönder", "Seçili nesneyi bir kat arkaya alır.", "Ctrl+["),
    'a_projset': ("Proje ayarları", "Çözünürlük, grid, FPS, toplam kare ve renkleri değiştirir.", None),
    'a_fit': ("Tuvale sığdır", "Görünümü tuvalin tamamı ekrana sığacak şekilde ayarlar.", "Ctrl+0"),
    'a_z100': ("%100 yakınlaştır", "Tuvali gerçek piksel boyutunda gösterir.", "Ctrl+1"),
    'a_clearkeys': ("Tüm hareketi temizle", "Seçili nesnenin bütün anahtar karelerini siler; nesne bulunduğu konumda sabit kalır.", None),
    'a_bg_video': ("Video / görüntü yükle", "Arka plana video ya da resim koyar. Sonra ← → ile kare kare gezip üstüne çizersin.", "Ctrl+B"),
    'a_bg_folder': ("Kare klasörü yükle", "Numaralı resim dizisini (PNG/JPG) arka plan olarak yükler.", None),
    'a_bg_set': ("Arka plan ayarları", "Tuval rengi, video/görüntü, görünürlük, sığdırma, başlangıç kayması ve katman konumu.", None),
    'a_bg_clear': ("Arka planı kaldır", "Yüklü video/görüntüyü projeden çıkarır.", None),
    'a_bg_off': ("Video başlangıç kayması", "Videonun hangi proje karesinde başlayacağını belirler.", None),
    'a_help': ("Hızlı başlangıç kılavuzu", "Video yükleme, çizim, hareket verme ve dışa aktarma adımlarını anlatır.", "F1"),
    # --- pencereler ------------------------------------------------------------------------------
    'd_ratio': ("En-boy oranı grubu", "Hazır çözünürlükler gruplanmıştır. 'Özel Boyut' ile genişlik/yüksekliği kendin yazarsın.", None),
    'd_preset': ("Hazır çözünürlük", "Listeden bir çözünürlük seçince genişlik ve yükseklik otomatik dolar.", None),
    'd_w': ("Genişlik", "Tuvalin genişliği (piksel).", None),
    'd_h': ("Yükseklik", "Tuvalin yüksekliği (piksel).", None),
    'd_grid': ("Grid boyutu", "Hücre boyutu. Tuval boyutuna göre izin verilen en küçük değer sınırlıdır (performans için).", None),
    'd_gridq': ("Hızlı grid", "Sık kullanılan grid boyutları. Alt sınırın altındakiler devre dışıdır.", None),
    'd_fps': ("Saniyedeki kare", "Oynatma ve video dışa aktarma hızı.", None),
    'd_frames': ("Toplam kare", "Animasyon uzunluğu = toplam kare / FPS saniye.", None),
    'd_bgc': ("Tuval rengi", "Tuvalin zemin rengi. Renk çemberiyle seçilir.", None),
    'd_gc': ("Grid rengi", "Izgara çizgilerinin rengi.", None),
    'd_kind': ("Nesne türü", "Hangi matematiksel nesneyi ekleyeceğini seç.", None),
    'd_formula': ("Hazır formül", "Örnek bir formül yükler; sonra değerleri değiştirebilirsin.", None),
    'd_px': ("Konum (orijin)", "Nesnenin orijininin tuvaldeki konumu. Formül nesnelerinde y yukarı doğrudur.", None),
    'd_rot': ("Döndürme", "Nesnenin başlangıç dönüşü (derece).", None),
    'e_fmt': ("Dışa aktarma biçimi", "PNG dizisi: her kare ayrı resim (saydam arka plan seçeneği var). MP4: tek video dosyası.", None),
    'e_range': ("Kare aralığı", "Hangi karelerin yazılacağı (1'den başlar).", None),
    'e_bg': ("Arka planı dahil et", "Yüklü video/görüntü tam çözünürlükte çıktıya eklenir.", None),
    'e_grid': ("Gridi dahil et", "Izgarayı da çıktıya çizer.", None),
    'e_alpha': ("Saydam arka plan", "Tuval rengi yerine saydam zemin yazar (yalnızca PNG). Videonun üstüne bindirmek için kullanışlıdır.", None),
    'b_color': ("Tuval rengi", "Tuvalin zemin rengi.", None),
    'b_load': ("Video / görüntü yükle", "Video (mp4, mov, avi, mkv, webm), resim ya da GIF seç.", None),
    'b_folder': ("Kare klasörü yükle", "PNG/JPG dizisi içeren bir klasör seç.", None),
    'b_clear': ("Arka planı kaldır", "Yüklü arka planı kaldırır.", None),
    'b_opacity': ("Görünürlük", "Arka planın opaklığı. Düşük değer çizimini daha belirgin yapar.", None),
    'b_fit': ("Sığdırma", "Sığdır: oranı korur, boşluk kalabilir. Doldur: oranı korur, taşanı keser. Esnet: oranı bozar.", None),
    'b_offset': ("Başlangıç karesi", "Video, proje zaman çizelgesinde bu karede başlar.", None),
    'b_above': ("Çizimlerin üstünde", "İşaretliyse arka plan çizimlerin ÜSTÜNE biner (referans görsel gibi).", None),
}


def tip_html(title, body, shortcut=None):
    sc = (" <span style='color:#7fd4ff'>[%s]</span>" % shortcut) if shortcut else ""
    body = body.replace("\n", "<br>")
    return ("<table width='320' cellpadding='3'><tr><td><b>%s</b>%s<br>%s</td></tr></table>" % (title, sc, body))


def tip(obj, key):
    """obj: QWidget ya da QAction. TIPS[key] açıklamasını bağlar."""
    t, b, s = TIPS[key]
    obj.setProperty(TIP_PROP, tip_html(t, b, s))
    return obj


def set_tip(obj, title, body, shortcut=None):
    obj.setProperty(TIP_PROP, tip_html(title, body, shortcut))
    return obj


# --------------------------------------------------------------------------------------
#  2 saniye bekleyince gösteren ipucu yöneticisi
# --------------------------------------------------------------------------------------
class TooltipManager(QObject):
    """
    Fare aynı öğenin üzerinde (en çok ~8 px titreme ile) TIP_DELAY_MS boyunca durursa açıklama gösterilir.
    Düğmeye tıklayınca, öğe değişince ya da fare hareket edince kapanır ve sayaç sıfırlanır.
    200 ms aralıkla yoklar; olay filtresi kullanmadığı için sisteme yük bindirmez.
    """

    def __init__(self, parent=None, delay_ms=TIP_DELAY_MS):
        super().__init__(parent)
        self.delay = delay_ms
        self._clock = QElapsedTimer()
        self._clock.start()
        self._target = None
        self._tip = None
        self._pos = QPoint(-9999, -9999)
        self._shown = False
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    # --- Qt'nin kendi (700 ms) ipuçlarını bastırmak için: araç çubuğu düğmelerine takılır ---------
    def eventFilter(self, obj, ev):
        return ev.type() == QEvent.ToolTip

    def suppress_native(self, widget):
        widget.installEventFilter(self)

    # ---------------------------------------------------------------------------------------------
    @staticmethod
    def find_tip(w, gpos):
        while w is not None:
            if isinstance(w, QMenu):
                a = w.actionAt(w.mapFromGlobal(gpos))
                if a is not None:
                    t = a.property(TIP_PROP)
                    if t:
                        return w, t
            t = w.property(TIP_PROP)
            if t:
                return w, t
            if isinstance(w, QToolButton) and w.defaultAction() is not None:
                t = w.defaultAction().property(TIP_PROP)
                if t:
                    return w, t
            w = w.parentWidget()
        return None, None

    def _cursor(self):
        return QCursor.pos()

    def _widget_at(self, pos):
        return QApplication.widgetAt(pos)

    def _reset(self, target, tip_text, pos):
        if self._shown:
            QToolTip.hideText()
            self._shown = False
        self._target, self._tip, self._pos = target, tip_text, QPoint(pos)
        self._clock.restart()

    def poll(self):
        if (QApplication.activeWindow() is None and QApplication.activePopupWidget() is None) \
                or QApplication.mouseButtons() != Qt.NoButton:
            self._reset(None, None, QPoint(-9999, -9999))
            return
        pos = self._cursor()
        target, text = self.find_tip(self._widget_at(pos), pos)
        moved = (pos - self._pos).manhattanLength() > 8
        if target is not self._target or text != self._tip or moved:
            self._reset(target, text, pos)
            return
        if text and not self._shown and self._clock.elapsed() >= self.delay:
            QToolTip.showText(pos + QPoint(12, 18), text, target)
            self._shown = True


# --------------------------------------------------------------------------------------
#  Hızlı başlangıç kılavuzu
# --------------------------------------------------------------------------------------
GUIDE_HTML = """
<h2 style='color:#4fc3f7'>Kavram Animasyon Stüdyosu — Hızlı başlangıç</h2>
<p>Bu program matematiksel olarak tanımlı nesneler çizer ve onları <b>anahtar karelerle</b> hareket ettirir.
İstersen bir videoyu arka plana koyup <b>kare kare</b> üzerine çizersin. Herhangi bir düğmenin üzerinde
<b>2 saniye</b> beklersen o düğmenin ne işe yaradığı gösterilir.</p>

<h3 style='color:#ffd24a'>1) Proje başlatma</h3>
<ul>
<li>Açılışta <b>çözünürlük</b> (hazır liste ya da özel), <b>grid boyutu</b>, <b>FPS</b> ve toplam <b>kare sayısı</b> seçilir.
Sağdaki önizleme tuvalin oranını gösterir.</li>
<li>Grid çok küçük yapılamaz: tuval boyutuna göre bir alt sınır vardır (en az 8 px). Bu, programı hızlı ve kararlı tutar.</li>
<li>Her şeyi sonradan <b>Proje → Proje ayarları</b> ile değiştirebilirsin.</li>
</ul>

<h3 style='color:#ffd24a'>2) Arka plana video / görüntü atma</h3>
<ol>
<li><b>Arka plan → Video / görüntü yükle</b> (Ctrl+B). Video, resim ya da kare klasörü seçebilirsin.</li>
<li>Program, proje boyutunu / kare sayısını / FPS'ini videoya eşitlemeyi önerir; genelde <b>Evet</b> demek en iyisidir.</li>
<li><b>←</b> ve <b>→</b> tuşlarıyla kare kare gez (Shift+← → : 10 kare, Home/End: baş/son). Boşluk: oynat.</li>
<li>Video yüklenince çizim kapsamı otomatik <b>"Sadece bu karede"</b> olur: her karede çizdiğin şey yalnızca o karede görünür
(klasik kare kare çizim). İstersen üstteki "Çizim kapsamı" kutusundan değiştir.</li>
<li><b>Arka plan → Arka plan ayarları</b>: görünürlük, sığdırma, videonun başlangıç karesi, tuval rengi ve
videonun çizimlerin üstünde mi altında mı olacağı.</li>
</ol>
<p style='color:#9ab'>Not: Ekranda hız için küçültülmüş kare gösterilir (en çok 1280 px); dışa aktarırken video
<b>tam çözünürlükte</b> okunur.</p>

<h3 style='color:#ffd24a'>3) Çizim</h3>
<ul>
<li>Soldaki araçlar: Seç (V), Kalem (P), Çizgi (L), Dikdörtgen (R), Elips (E), Çokgen (G), Yıldız (S), Eğri (B),
Silgi (X), Kaydır (H), Damlalık (I).</li>
<li>Çizilen her şey düzenlenebilir bir <b>nesnedir</b>. Sağdaki panelde nesnenin konumunu, dönüşünü, ölçeğini ve
<b>matematiksel parametrelerini</b> (yarıçap, nokta listesi, formül...) değiştirirsin.</li>
<li><b>M</b> tuşu: formülle nesne ekle. Örnek: y = 3*sin(x), kalp, spiral, gül eğrisi.</li>
<li>Renk: sağ paneldeki kaydırıcılar, hex kutusu, palet, son kullanılanlar ve <b>Renk çemberi</b> düğmesi.
Çizgi ve dolgu ayrı ayrı seçilir.</li>
<li>Fare tekerleği yakınlaştırır, orta tuş kaydırır. Ctrl+0: tuvale sığdır.</li>
</ul>

<h3 style='color:#ffd24a'>4) Hareket ettirme (anahtar kareler)</h3>
<ol>
<li>Bir nesne seç. İstediğin başlangıç karesinde <b>K</b> tuşuna bas (anahtar kare eklenir, zaman çizelgesinde sarı işaret çıkar).</li>
<li>Başka bir kareye git (örneğin 24. kare), nesneyi <b>taşı / döndür / ölçekle</b>, tekrar <b>K</b>'ye bas.</li>
<li>Oynat (Boşluk): nesne iki anahtar arasında kendiliğinden hareket eder.</li>
<li>Kolay yol: <b>Oto-anahtar</b>'ı aç; sonra sadece kareye git ve nesneyi oynat — anahtarlar kendiliğinden oluşur.</li>
<li>Geçiş türü: doğrusal, yumuşak, yavaş başla/bitir, sabit tut. Ctrl+← / Ctrl+→: bir önceki/sonraki anahtara atla.
Shift+K: bu karedeki anahtarı sil.</li>
<li><b>Soğan kabuğu</b> (O): önceki kareler kırmızı, sonrakiler yeşil hayalet görünür; hareketin akışını görürsün.</li>
</ol>

<h3 style='color:#ffd24a'>5) Kaydetme ve dışa aktarma</h3>
<ul>
<li><b>Ctrl+S</b> projeyi .kanim olarak kaydeder. Program her 90 saniyede kurtarma kopyası alır; beklenmedik bir kapanma olursa
sonraki açılışta projeni geri getirmeyi önerir.</li>
<li><b>Ctrl+E</b>: PNG dizisi ya da MP4 video. İlk/son kareyi seç; arka plan videosunu ve gridi dahil edip etmemeyi seç.
PNG'de saydam zemin seçeneği vardır.</li>
</ul>

<h3 style='color:#ffd24a'>Kısayollar</h3>
<table cellpadding='3'>
<tr><td><b>← →</b></td><td>kare değiştir</td><td><b>Shift+← →</b></td><td>10 kare</td></tr>
<tr><td><b>Boşluk</b></td><td>oynat / durdur</td><td><b>K / Shift+K</b></td><td>anahtar ekle / sil</td></tr>
<tr><td><b>Ctrl+Z / Y</b></td><td>geri / ileri al</td><td><b>Ctrl+D</b></td><td>çoğalt</td></tr>
<tr><td><b>Ctrl+G</b></td><td>grid göster</td><td><b>Ctrl+Shift+G</b></td><td>ızgaraya yapış</td></tr>
<tr><td><b>O</b></td><td>soğan kabuğu</td><td><b>F1</b></td><td>bu kılavuz</td></tr>
</table>
"""


class GuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hızlı başlangıç kılavuzu")
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(False)
        tb.setHtml(GUIDE_HTML)
        lay.addWidget(tb, 1)
        row = QHBoxLayout()
        self.never = QCheckBox("Açılışta bir daha gösterme")
        self.never.setChecked(QSettings(SETTINGS_ORG, SETTINGS_APP).value("guide_seen", False, type=bool))
        row.addWidget(self.never)
        row.addStretch(1)
        b = QPushButton("Kapat")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)

    def done(self, r):
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("guide_seen", self.never.isChecked())
        super().done(r)


def guide_seen():
    return QSettings(SETTINGS_ORG, SETTINGS_APP).value("guide_seen", False, type=bool)
