#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kavram Animasyon Stüdyosu — başlatıcı

Çalıştırma:   python Kavram_Animasyon.py [proje.kanim]
Gereksinim:   pip install PyQt5 opencv-python numpy      (video için ffmpeg de yedek olarak kullanılır)

Modüller (aynı klasörde durmalı):
  kanim_math.py    saf matematik: grid sınırları, çözünürlük listesi, güvenli formül, sadeleştirme
  kanim_frames.py  kare okuma: bayt bütçeli önbellek, kare doğruluklu okuyucu
  kanim_video.py   arka plan kaynakları (video/görüntü/klasör), arka plan iş parçacığı
  kanim_core.py    nesne modeli (Obj, Project), geometri
  kanim_canvas.py  çizim tuvali
  kanim_widgets.py renk çemberi, proje/arka plan/dışa aktarma pencereleri, zaman çizelgesi
  kanim_help.py    Türkçe açıklamalar, 2 saniye ipucu yöneticisi, kılavuz
  kanim_export.py  parça parça dışa aktarma
  kanim_guard.py   çökme koruması (hata yakalayıcı, faulthandler)
  kanim_app.py     ana pencere
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kanim_app import main  # noqa: E402

if __name__ == "__main__":
    main()
