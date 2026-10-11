# -*- coding: utf-8 -*-
"""
Kavram Animasyon — çökme koruması

PyQt5 (5.5+), bir slot / paintEvent / olay işleyicide yakalanmamış Python hatası olursa ve
sys.excepthook özel değilse programı qFatal() ile DOĞRUDAN KAPATIR. Eski sürümdeki "çöktü"
şikâyetlerinin en yaygın sebebi budur. Burada:

  * sys.excepthook + threading.excepthook   -> hata kayda yazılır, program ÇALIŞMAYA DEVAM EDER
  * faulthandler                            -> yerel (C++) çökmelerde iz bırakır
  * kayıt dosyası boyutu sınırlıdır
"""

import os
import sys
import time
import threading
import traceback
import faulthandler

LOG_DIR = os.path.join(os.path.expanduser('~'), '.kavram_anim')
ERROR_LOG = os.path.join(LOG_DIR, 'error.log')
FAULT_LOG = os.path.join(LOG_DIR, 'fault.log')
AUTOSAVE_PATH = os.path.join(LOG_DIR, 'autosave.kanim')
MAX_LOG_BYTES = 512 * 1024

_notify = None            # arayüze bildirim geri çağrısı (ana pencere ayarlar)
_last_note = 0.0
_fault_file = None


def ensure_dir():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def log_error(text):
    if not ensure_dir():
        return
    try:
        if os.path.exists(ERROR_LOG) and os.path.getsize(ERROR_LOG) > MAX_LOG_BYTES:
            os.replace(ERROR_LOG, ERROR_LOG + ".old")
        with open(ERROR_LOG, 'a', encoding='utf-8') as f:
            f.write("[%s]\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def set_notifier(fn):
    global _notify
    _notify = fn


def _report(text, short):
    global _last_note
    log_error(text)
    now = time.time()
    if _notify is not None and now - _last_note > 2.0:       # arayüzü hata yağmuruna tutma
        _last_note = now
        try:
            _notify(short)
        except Exception:
            pass


def install():
    """Programın en başında (QApplication'dan önce) çağrılır."""
    global _fault_file
    if ensure_dir():
        try:
            if os.path.exists(FAULT_LOG) and os.path.getsize(FAULT_LOG) > MAX_LOG_BYTES:
                os.remove(FAULT_LOG)
            _fault_file = open(FAULT_LOG, 'a')
            faulthandler.enable(_fault_file)
        except Exception:
            pass

    def hook(etype, value, tb):
        if issubclass(etype, KeyboardInterrupt):
            sys.__excepthook__(etype, value, tb)
            return
        text = ''.join(traceback.format_exception(etype, value, tb))
        _report(text, "%s: %s" % (etype.__name__, value))

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        text = ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        _report("[iş parçacığı %s]\n%s" % (getattr(args.thread, 'name', '?'), text),
                "%s: %s" % (args.exc_type.__name__, args.exc_value))

    sys.excepthook = hook
    threading.excepthook = thread_hook
